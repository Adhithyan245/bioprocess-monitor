# Bioprocess Monitor

A small dashboard that watches fermentation batches and raises an alarm when a
sensor starts behaving unlike a normal batch. It is a portfolio project. It is
built to show the methods clearly and report their results honestly, not to run
a real plant.

**What you can do with it:** pick a batch and see temperature, pH, dissolved
oxygen and agitation over time, plus aeration rate and head pressure for the
IndPenSim batches. Each chart shows the band where a normal batch
usually sits, the points that left it, the alarms raised, and any missing
readings. Tables summarise each batch.

---

## 1. The data

The dashboard can show two datasets. You switch between them in the sidebar.

### IndPenSim (public, simulated)

IndPenSim is a published computer simulation of a 100,000-litre industrial
penicillin fermentation. Its authors released 100 simulated batches:

| Batches | How they were run |
|---|---|
| 1–30 | Fixed recipe |
| 31–60 | Operator control |
| 61–90 | Advanced automatic control (Raman spectroscopy) |
| 91–100 | **Contain process faults** (labelled by the authors) |

- **Source:** Goldrick et al., *Data for: Modern day monitoring and control challenges outlined on an industrial-scale benchmark fermentation process*, Mendeley Data, [doi:10.17632/pdnjz7zz5x.2](https://data.mendeley.com/datasets/pdnjz7zz5x/2).
- **Licence:** CC BY 4.0. You may reuse and share it if you credit the authors.
- **Please cite:** Goldrick S. et al. (2015) *The development of an industrial-scale fed-batch fermentation simulation*, Journal of Biotechnology 193:70–82. Also Goldrick S. et al. (2019) *Modern day monitoring and control challenges outlined on an industrial-scale benchmark fermentation process*, Computers and Chemical Engineering 130:106471.

The original download is about 504 MB, mostly Raman spectra. This project keeps
only the columns it needs, in `data/indpensim_extract.csv.gz` (0.9 MB).

Notes on the raw file, found while building this:
- **The CSV header is out of step with its data.** The header has 2,239 column
  names but each row has 2,237 values, so names after column 32 point at the
  wrong data. We read columns by position and identified the batch-number
  column from the data itself.
- **The column labelled "Fault flag" is not a 0/1 flag.** The fault answer key
  comes from the "Fault reference" column instead.
- **Agitation is constant at 100 rpm in every batch.** The simulator does not
  vary it, so on this dataset the agitation chart is a flat line and cannot
  detect anything.
- **Aeration rate and head pressure follow recipe steps.** Aeration moves
  between about six fixed levels (30–75 L/h) and pressure between 0.6 and
  1.1 bar, at nearly the same times in every normal batch. They behave more like
  set points than noisy measurements.
- **Temperature is converted from kelvin to °C.**

### Synthetic (made up, clearly labelled)

`biomon/synthetic.py` generates 40 fake 100-hour batches with a simple model.
Cells grow along an S-shaped curve, which makes oxygen fall, agitation rise to
compensate, pH drift down slightly, and temperature rise slightly. Each batch
gets small random differences and measurement noise, plus a few randomly
missing readings.

Ten of the batches have one **injected fault**, so we know exactly what went
wrong, where and when:

| Fault | What happens | Size |
|---|---|---|
| Cooling failure | Temperature steps up | +0.4 °C |
| Base pump drift | pH slowly drifts down | −0.004 pH per hour |
| DO probe fouling | Oxygen reading slowly drifts down | −0.15 % per hour |
| Agitator stall | Agitator freezes at its current speed | — |
| Sensor dropout | One sensor sends nothing for 3–6 hours | — |

This dataset exists to **test** the methods. Everywhere it appears, it is
labelled SYNTHETIC.

---

## 2. How it works

### Storage: SQLite + SQL

All readings go into a small SQLite database file, one row per reading. If a
reading never arrived, its row is still there with an empty value, so missing
data is easy to count.

The analysis questions are plain SQL files in `sql/`:

| File | Question it answers |
|---|---|
| `batch_summary.sql` | For each batch and sensor: min / mean / max, missing count, out-of-spec count, alarms |
| `out_of_spec.sql` | Which readings broke the spec limits in the config file? |
| `out_of_control.sql` | Which readings left the statistical control band? |
| `missing_readings.sql` | Where are the gaps, grouped into continuous stretches? |
| `fleet_overview.sql` | One line per batch, for the "All batches" tab |

### Two kinds of limits

- **Spec limits** (`config/sensor_limits.json`) are the acceptable range set by
  people, e.g. "temperature must stay between 29 and 31 °C". The IndPenSim spec
  limits in the config were **chosen for this project for illustration**; they
  are not from the dataset's authors.
- **Control limits** are learned from good batches and describe what *normal*
  looks like. A process can be inside spec but still behaving abnormally, and
  that is often the earliest warning. The synthetic cooling failure is an
  example: it never leaves the 29–31 °C spec, but it is caught immediately.

### Shewhart control chart (time-varying)

A batch follows a curve over time. Oxygen, for example, starts high and falls as
cells grow. One flat band for the whole batch would therefore be far too wide.
Instead, at **each moment of the batch** we take the readings of the good
batches at that moment and compute their average and spread (standard
deviation, σ). The normal band is **average ± k·σ**. This is sometimes called a
"golden batch" envelope.

The band is lightly smoothed over time (5 samples) to reduce noise. Aeration and
pressure are **not** smoothed, because they change in sharp steps: smoothing
would blur each step and put a false flag on either side of it.

### EWMA drift detection

A slow drift can stay inside the band for hours. The **EWMA** (exponentially
weighted moving average) is a running average that gives 20 % weight to each
new point and 80 % to everything before it. Random noise averages out, while a
steady drift builds up and crosses the EWMA's own band sooner. The EWMA band is
learned from the good batches in the same way.

### Flags, alarms and missing readings

- A **flag** is a single reading outside the band, shown as an orange dot.
- An **alarm** is **3 or more consecutive flags on the same side**, shown as a
  red cross. Single flags happen by chance; three in a row rarely do. Because
  the EWMA remembers recent readings, its alarms can continue for a short time
  after a reading has returned to normal.
- A **missing reading** is shown as a grey tick at the bottom of the chart and
  listed in the missing-gaps table.

### Choosing k: calibration instead of the textbook "3σ"

The textbook rule is k = 3. On real-looking batches it produced far too many
false alarms: 38 of 45 normal IndPenSim test batches and 5 of 10 normal
synthetic ones. So k is **calibrated using only the good (baseline) batches**:

1. Take one baseline batch out and learn the limits from the rest.
2. Measure how far the left-out batch strays: the largest k at which it would
   still raise an alarm.
3. Repeat for every baseline batch and every sensor.
4. Give **each sensor its own k**, so a calm sensor isn't judged by a noisy
   one's threshold. All sensors' k values sit at the same rank among their own
   baseline results. That rank is pushed as low as possible while, **across all
   sensors together, no more than 5 %** of baseline batches would alarm. k is
   never set below the textbook value of 3.

The test batches are never used to choose k. That keeps the results below
honest. Each chart title in the dashboard shows the k used for that sensor.

### Train / test split

| Dataset | Learns the limits ("baseline") | Scored only ("test") |
|---|---|---|
| Synthetic | 20 normal batches | 10 normal + 10 faulty |
| IndPenSim | 45 normal batches (odd numbers 1–89) | 45 normal (even numbers 2–90) + 10 faulty (91–100) |

The split was fixed before any results were seen.

---

## 3. Results

Full tables are in [`reports/`](reports/) and in the dashboard's "Detection
results" tab. They are regenerated by every build.

### Synthetic data: the methods work on the faults they were designed for

- **All 10 faulty batches detected**, each on the correct sensor.
- Thresholds after calibration: Shewhart k = 3 for every sensor; EWMA k = 3
  except pH (3.68) and agitation (4.26).
- Detection delays after the fault starts:
  - cooling failure (step): **0 h**
  - pH drift: 4.0 h and 8.8 h (found first by EWMA)
  - agitator stall: 9.8 h and 5.8 h
  - **DO probe fouling: 30.0 h and 17.5 h** (found first by EWMA), slow,
    because oxygen naturally varies a lot between batches, so a small drift
    takes a long time to stand out
  - sensor dropouts: found immediately as missing-data gaps
- **False alarms:**
  - 3 of 10 normal test batches had an alarm, all on pH, from batches whose
    whole run sat unusually high or low.
  - On 100 brand-new normal batches, **16 % had a false alarm**, against a target
    of 5 %. This is a **known limitation**. Calibrating from only 20 good
    batches gives a noisy estimate, and k comes out slightly too low. Giving
    each sensor its own k made this a little worse (it was 12 % with one shared
    k), because each k is now estimated separately from the same few batches.
    More good batches would help.

### IndPenSim: a partial result

- **5 of 10 faulty batches detected; 4 of 45 normal test batches (9 %) raised a
  false alarm**, on temperature or DO. That is above the 5 % target, even
  though no baseline batch would alarm in leave-one-out: the same small-sample
  effect as on the synthetic data.
  - Batches 94, 99 and 100: aeration falls to 20 L/h, below any normal batch,
    and is caught **within 0.2 h**.
  - Batches 93 and 96: temperature rises to about 28.3 °C during the fault and
    is caught about **8 h** after onset. Height alone isn't the giveaway (one
    normal batch reaches 27.7 °C); what stands out is a sustained rise at a time
    when normal batches stay near 24.8 °C.
  - Batches 91, 92, 95, 97 and 98: **missed**.
- **Per-sensor thresholds** (k for Shewhart / EWMA): aeration, pressure and
  agitation 3 / 3, DO 6.1 / 6.3, temperature 20.9 / 19.3, **pH 84.7 / 156**.
  Several batches labelled *normal* contain pH upsets lasting several hours that
  are as large as the labelled faults. For example, normal batch 67 dips to pH
  5.40, while faulty batch 92 only reaches pH 5.48. So pH needs an enormous
  threshold, and in practice it detects nothing here.
- **How we got here** (each step scored on the same test batches):

| Version | Faulty batches detected | Normal batches with a false alarm |
|---|---|---|
| 4 sensors, one shared k (69σ) | 2/10 (92, 98 on pH, ~67 h late) | 0/45 |
| + aeration and pressure, one shared k (69σ) | 5/10 (adds 94, 99, 100) | 0/45 |
| + a separate k per sensor (current) | 5/10 (93, 94, 96, 99, 100) | 4/45 |

  Per-sensor thresholds are **a trade, not a clear win**. Temperature's own k
  (21σ instead of 69σ) catches the two temperature excursions in 93 and 96,
  which the shared k missed even at 28 °C. But pH's k had to rise (85σ instead
  of 69σ), losing 92 and 98, and false alarms went from 0 to 4.
- **Pressure did not help.** In batches 93 and 96 the pressure is 1.1 bar during
  the fault window, but every normal batch is also at 1.1 bar at that time (a
  recipe step), so there is nothing unusual to see.
- **Caveat:** the aeration faults are applied to the aeration rate itself, so
  spotting them there is easier than inferring a fault from its effect on the
  culture. In a real plant this would still be a useful alarm (an air flow meter
  disagreeing with the recipe).
- For comparison, if one k were shared by every sensor (shown for
  transparency only; k was not chosen from this table):

| Shared k | Faulty batches detected | Normal batches with a false alarm |
|---|---|---|
| 3 (textbook) | 10/10 | 38/45 |
| 5 | 9/10 | 20/45 |
| 10 | 7/10 | 8/45 |
| 40 | 7/10 | 0/45 |
| 70 | 5/10 | 0/45 |

- **What would probably help** (not done here): more IndPenSim variables (feed
  rates, off-gas, coolant), multivariate methods (e.g. PCA-based monitoring)
  that look at all sensors together, aligning batches by growth phase rather
  than clock time, and more good batches to calibrate from.

---

## 4. Limitations

- The IndPenSim data is **simulated**, and the synthetic data is **made up**. No
  real plant data is used.
- Each sensor is monitored **on its own**. Faults that only show up as an unusual
  *combination* of sensors are missed.
- Batches are compared **at the same clock time**. A batch that simply grows a
  little faster or slower looks abnormal during fast-changing phases.
- Limits learned from **few good batches** are imprecise, as the 16 % (synthetic)
  and 9 % (IndPenSim) false-alarm results show.
- The 3-in-a-row alarm rule **cannot catch a single-point spike**. That is
  deliberate, to reduce false alarms.
- The answer key (normal/fault) is shown in the dashboard for learning purposes.
  A real monitoring system would not have it.

---

## 5. How to run it

You need Python 3.10 or newer. Open PowerShell in this folder and run these
commands.

Install the libraries:

```powershell
pip install -r requirements.txt
```

Build both databases and the detection reports (takes about a minute):

```powershell
python -m biomon.build
```

Open the dashboard in your browser:

```powershell
streamlit run app.py
```

Run the validation tests (expect "21 passed, 1 xfailed"; the expected failure is
the 16 % known limitation above):

```powershell
python -m pytest -v
```

**Optional:** to rebuild the IndPenSim extract from the original download, save
`100_Batches_IndPenSim.zip` from the Mendeley link above into `data/raw/`, then
run:

```powershell
python -m biomon.indpensim
```

To change spec limits, the k values, the EWMA weight or the 3-in-a-row rule,
edit `config/sensor_limits.json` and rebuild.

---

## 6. Project layout

```
app.py                     Streamlit dashboard
config/sensor_limits.json  Spec limits and monitoring settings
sql/                       Database schema and analysis queries
biomon/synthetic.py        SYNTHETIC data generator with injected faults
biomon/indpensim.py        Extracts IndPenSim's six sensors
biomon/db.py               SQLite loading and running the SQL files
biomon/monitoring.py       Control limits, EWMA, alarms, calibration
biomon/build.py            Runs everything end to end
biomon/report.py           Scores alarms against the answer key
tests/                     pytest validation
reports/                   Generated detection results
data/                      IndPenSim extract (+ generated databases)
```

## 7. Glossary

- **Batch:** one complete fermentation run, from inoculation to harvest.
- **Dissolved oxygen (DO):** how much oxygen is dissolved in the broth; cells need it to grow.
- **Agitation:** stirrer speed. Faster stirring mixes more oxygen in.
- **σ (sigma), standard deviation:** a measure of how spread out values normally are.
- **Control limits:** the normal band learned from good batches.
- **Spec limits:** the acceptable range set by people.
- **False alarm:** an alarm on a batch that was actually fine.
- **Detection delay:** time from when a fault started to the first alarm.
