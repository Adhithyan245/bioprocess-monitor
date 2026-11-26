import pytest

from biomon import build, db, synthetic


@pytest.fixture(scope="session")
def cfg():
    return db.load_config()


@pytest.fixture(scope="session")
def synth(tmp_path_factory, cfg):
    """Build the synthetic database once, in a temporary folder."""
    data = synthetic.generate()
    conn, scored, alarms = build.build("synthetic", tmp_path_factory.mktemp("db") / "synthetic.db",
                                       data=data, cfg=cfg)
    return {"conn": conn, "scored": scored, "alarms": alarms, "data": data,
            "settings": build.settings_from_db(conn, cfg)}
