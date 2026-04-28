"""
ADMS — Flask API, Socket.IO realtime, MongoDB (or memory), Python AI screening.
Run from backend/:  python app.py
"""

from __future__ import annotations

import os
import random
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from bson import ObjectId
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request
from flask_cors import CORS
from flask_socketio import SocketIO, emit
from pymongo import ASCENDING, MongoClient
from pymongo.errors import PyMongoError

from ai.scoring import anomaly_score, doping_suspected, risk_status

load_dotenv()

BACKEND = Path(__file__).resolve().parent
ROOT = BACKEND.parent
FRONTEND = ROOT / "frontend"

TICK_SEC = 3.0
SPARK_MAX = 28
READING_CAP = 800
ALERT_COOLDOWN = 25.0

SEED = [
    {"key": "a1", "name": "Maya Chen", "sport": "Track — 800m", "baseline": {"hr": 54, "hrv": 68, "hb": 14.2, "cortisol": 12}},
    {"key": "a2", "name": "Jonas Okonkwo", "sport": "Cycling", "baseline": {"hr": 48, "hrv": 82, "hb": 15.1, "cortisol": 10}},
    {"key": "a3", "name": "Elena Rossi", "sport": "Swimming", "baseline": {"hr": 58, "hrv": 55, "hb": 13.8, "cortisol": 15}},
    {"key": "a4", "name": "Alex Morgan", "sport": "Football", "baseline": {"hr": 52, "hrv": 62, "hb": 14.5, "cortisol": 11}},
]


def walk(v: float, lo: float, hi: float, sigma: float) -> float:
    x = v + (random.random() - 0.5) * sigma
    return max(lo, min(hi, round(x * 10) / 10))


class MemoryStore:
    def __init__(self) -> None:
        self.readings: list[dict] = []
        self.alerts: list[dict] = []
        self._cool: dict[str, float] = {}

    def insert_reading(self, doc: dict) -> None:
        doc = {**doc, "_id": ObjectId(), "ts": datetime.now(timezone.utc)}
        self.readings.insert(0, doc)
        self.readings = self.readings[:READING_CAP]

    def insert_alert(self, doc: dict) -> None:
        doc = {**doc, "_id": ObjectId(), "ts": datetime.now(timezone.utc)}
        self.alerts.insert(0, doc)
        self.alerts = self.alerts[:150]

    def recent_readings(self, n: int) -> list[dict]:
        return self.readings[:n]

    def recent_alerts(self, n: int) -> list[dict]:
        return self.alerts[:n]

    def clear_readings(self) -> int:
        k = len(self.readings)
        self.readings.clear()
        return k


class MongoStore:
    def __init__(self, uri: str, db_name: str) -> None:
        self._c = MongoClient(uri, serverSelectionTimeoutMS=5000)
        self._c.admin.command("ping")
        self.db = self._c[db_name]
        self.readings = self.db.readings
        self.alerts = self.db.alerts
        self.athletes = self.db.athletes
        self.readings.create_index([("ts", ASCENDING)])
        self._cool: dict[str, float] = {}

    def seed(self) -> None:
        for a in SEED:
            self.athletes.update_one({"key": a["key"]}, {"$setOnInsert": a}, upsert=True)

    def insert_reading(self, doc: dict) -> None:
        doc["ts"] = datetime.now(timezone.utc)
        self.readings.insert_one(doc)
        while self.readings.count_documents({}) > READING_CAP:
            o = self.readings.find_one(sort=[("ts", ASCENDING)])
            if not o:
                break
            self.readings.delete_one({"_id": o["_id"]})

    def insert_alert(self, doc: dict) -> None:
        doc["ts"] = datetime.now(timezone.utc)
        self.alerts.insert_one(doc)

    def recent_readings(self, n: int) -> list[dict]:
        return list(self.readings.find().sort("ts", -1).limit(n))

    def recent_alerts(self, n: int) -> list[dict]:
        return list(self.alerts.find().sort("ts", -1).limit(n))

    def clear_readings(self) -> int:
        r = self.readings.delete_many({})
        return int(r.deleted_count)


def connect_store():
    uri = os.environ.get("MONGODB_URI", "mongodb://127.0.0.1:27017")
    name = os.environ.get("MONGODB_DB", "adms")
    try:
        m = MongoStore(uri, name)
        m.seed()
        print(f"MongoDB OK: {name}")
        return m
    except (PyMongoError, Exception) as e:
        print(f"MongoDB unavailable ({e}); using in-memory store.")
        return MemoryStore()


store = connect_store()

_vitals: dict[str, dict] = {}
_spark: list[float] = [52 + random.random() * 8 for _ in range(SPARK_MAX)]
_lock = threading.Lock()
_last_state: dict | None = None
_last_alert_ts: dict[str, float] = {}


def ensure_vitals(keys: list[str]) -> None:
    for row in SEED:
        k = row["key"]
        if k not in _vitals:
            b = row["baseline"]
            _vitals[k] = {"hr": float(b["hr"]), "hrv": float(b["hrv"]), "hb": float(b["hb"]), "cortisol": float(b["cortisol"])}


def tick() -> dict:
    global _spark, _last_state
    rows = []
    sum_hr = 0.0
    max_score = 0.0
    ensure_vitals([s["key"] for s in SEED])

    with _lock:
        for row in SEED:
            k = row["key"]
            b = row["baseline"]
            v = _vitals[k]
            v["hr"] = walk(v["hr"], 38, 118, 5)
            v["hrv"] = walk(v["hrv"], 32, 105, 7)
            v["hb"] = walk(v["hb"], 12.4, 17.2, 0.28)
            v["cortisol"] = walk(v["cortisol"], 5.5, 30, 2.2)
            if random.random() < 0.03:
                v["hb"] = min(17.5, v["hb"] + 1.1)
                v["cortisol"] = min(32, v["cortisol"] + 4)

            score, flags = anomaly_score(v, b)
            status = risk_status(score, flags)
            max_score = max(max_score, score)
            sum_hr += v["hr"]

            rows.append(
                {
                    "key": k,
                    "name": row["name"],
                    "sport": row["sport"],
                    "hr": v["hr"],
                    "hrv": v["hrv"],
                    "hb": v["hb"],
                    "cortisol": v["cortisol"],
                    "score": score,
                    "flags": flags,
                    "status": status,
                }
            )

            store.insert_reading(
                {
                    "athlete_key": k,
                    "athlete_name": row["name"],
                    "vitals": dict(v),
                    "score": score,
                    "flags": flags,
                    "status": status,
                }
            )

            now = time.time()
            if doping_suspected(score, flags):
                if now - _last_alert_ts.get(k, 0) >= ALERT_COOLDOWN and random.random() < 0.55:
                    _last_alert_ts[k] = now
                    msg = (
                        f"Elevated risk — score {score:.2f}, flags: {', '.join(flags) if flags else 'composite'}"
                    )
                    store.insert_alert(
                        {
                            "athlete_key": k,
                            "athlete_name": row["name"],
                            "message": msg,
                            "severity": "high" if score >= 0.85 else "medium",
                            "score": score,
                            "flags": flags,
                        }
                    )

        avg_hr = sum_hr / max(len(rows), 1)
        _spark.append(avg_hr)
        if len(_spark) > SPARK_MAX:
            _spark.pop(0)
        spark = list(_spark)

    alerts_raw = store.recent_alerts(20)
    alerts = []
    for a in alerts_raw:
        ts = a.get("ts")
        alerts.append(
            {
                "id": str(a.get("_id", "")),
                "ts": int(ts.timestamp() * 1000) if ts else 0,
                "athlete": a.get("athlete_name", ""),
                "message": a.get("message", ""),
                "severity": a.get("severity", "medium"),
            }
        )

    out = {
        "athletes": rows,
        "avgHr": round(avg_hr, 2),
        "maxScore": round(max_score, 4),
        "sparkHistory": spark,
        "alerts": alerts,
        "alertCount": len(alerts),
        "mongo": isinstance(store, MongoStore),
        "ai": "python",
    }
    _last_state = out
    return out


# Standard Flask static: /static/css/... and /static/js/... (no conflict with "/").
app = Flask(
    __name__,
    static_folder=str(FRONTEND),
    static_url_path="/static",
    template_folder=str(FRONTEND),
)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "adms-dev-key")
CORS(app, resources={r"/api/*": {"origins": "*"}})
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/health")
def health():
    return jsonify({"ok": True, "mongo": isinstance(store, MongoStore)})


@app.route("/api/state")
def state():
    if _last_state:
        return jsonify(_last_state)
    return jsonify(tick())


@app.route("/api/readings")
def readings():
    n = min(int(request.args.get("limit", 40)), 100)
    raw = store.recent_readings(n)
    out = []
    for r in raw:
        ts = r.get("ts")
        out.append(
            {
                "id": str(r.get("_id", ""))[:12] + "…",
                "ts": int(ts.timestamp() * 1000) if ts else 0,
                "athlete": r.get("athlete_name", ""),
                "vitals": r.get("vitals", {}),
                "score": r.get("score"),
                "flags": r.get("flags", []),
                "status": r.get("status", ""),
            }
        )
    return jsonify({"readings": out})


@app.route("/api/readings", methods=["DELETE"])
def clear_readings():
    n = store.clear_readings()
    return jsonify({"cleared": n})


def loop():
    time.sleep(0.4)
    while True:
        try:
            st = tick()
            socketio.emit("state", st)
        except Exception as e:
            print("tick error:", e)
        time.sleep(TICK_SEC)


@socketio.on("connect")
def on_connect():
    if _last_state:
        emit("state", _last_state)


if __name__ == "__main__":
    tick()
    threading.Thread(target=loop, daemon=True).start()
    port = int(os.environ.get("PORT", "5000"))
    host = os.environ.get("HOST", "0.0.0.0")
    print(f"ADMS → http://127.0.0.1:{port}/")
    socketio.run(app, host=host, port=port, allow_unsafe_werkzeug=True)
