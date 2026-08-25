import os
import psycopg
import time
import datetime
import numpy as np

from ipi_ecs.subsystems.experiment_controller import ExperimentReader

DDL = """
CREATE TABLE IF NOT EXISTS runs (
    uuid UUID PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    timestamp TIMESTAMP NOT NULL,
    end_reason TEXT,
    dose FLOAT,
    runtime FLOAT,
    eff_doserate FLOAT,
    target_dose FLOAT,
    target_runtime FLOAT,
    operator TEXT,
    zr_filter_id TEXT
);
CREATE TABLE IF NOT EXISTS statistics_weekly (
    week_start DATE PRIMARY KEY,
    run_count INT NOT NULL,
    runs_over_2mj INT NOT NULL,
    runs_over_5mj INT NOT NULL,
    success_count INT NOT NULL,
    successes_over_2mj INT NOT NULL,
    successes_over_5mj INT NOT NULL,
    abort_count INT NOT NULL,
    failure_count INT NOT NULL,
    failures_over_2mj INT NOT NULL,
    failures_over_5mj INT NOT NULL,
    success_rate FLOAT NOT NULL,
    success_rate_over_2mj FLOAT NOT NULL,
    success_rate_over_5mj FLOAT NOT NULL,
    avg_doserate FLOAT NOT NULL,
    cumulative_dose FLOAT NOT NULL,
    cumulative_runtime FLOAT NOT NULL
);
"""

SAVE_PATH = os.path.join(os.environ["EUVL_PATH"], "datasets")
DB_URL = os.environ["DASHBOARD_DB_URL"]

USER_STOP_KEY = "Stopped by user."

class DashboardWorker:
    def __init__(self, save_path, db_url):
        self.db_url = db_url
        self.conn = psycopg.connect(db_url)
        self.conn.execute(DDL)
        self.conn.commit()

        self.exp_reader = ExperimentReader(save_path, "exposure")

    def repopulate(self):
        """
        Clear the runs table, query all experiments with a dose tag, and insert them into the runs table.
        """
        results = self.exp_reader.query({
            "tags": {
                "dose": {"min": 0},
            }
        })
        
        print(f"Found {len(results)} experiments with dose tag")

        if len(results) == 0:
            print("Failed to load anything, aborting.")
            return

        print("Clearing tables...")
        self.conn.execute("DELETE FROM runs;")
        self.conn.execute("DELETE FROM statistics_weekly;")
        self.conn.commit()

        print("Inserting runs into the database...")
        
        for result in results:
            uuid = result.get_tags().get("run")
            name = result.get_name()
            description = result.get_description()

            tags = result.get_tags()

            """start_time = result.get_metadata().created_at
            end_time = result.get_end_metadata().end_time if result.get_end_metadata() else None
            end_reason = result.get_end_metadata().end_reason if result.get_end_metadata() else None

            Do not use metadata since it requires the record to be fully downloaded.
            Use tags instead, which are quickloaded instead.
            """

            timestamp = result.get_record().get_timestamp() # UNIX timestamp of record creation, good enough for the dashboard
            end_reason = tags.get("end_reason")

            dose = tags.get("dose")
            runtime = tags.get("runtime")

            target_dose = tags.get("target_dose")
            target_runtime = tags.get("target_time")

            eff_doserate = float(dose) / float(runtime) if dose is not None and runtime is not None and float(runtime) > 0 else None

            operator = tags.get("operator")
            zr_filter_id = tags.get("zr_filter")

            print(f"Inserting run: {uuid}, name: {name}, dose: {dose}, runtime: {runtime}, target_dose: {target_dose}, target_runtime: {target_runtime}, operator: {operator}, zr_filter_id: {zr_filter_id}")
            self.conn.execute(
                "INSERT INTO runs (uuid, name, description, timestamp, end_reason, dose, runtime, target_dose, target_runtime, eff_doserate, operator, zr_filter_id) VALUES (%s, %s, %s, to_timestamp(%s), %s, %s, %s, %s, %s, %s, %s, %s);",
                (uuid, name, description, timestamp, end_reason, dose, runtime, target_dose, target_runtime, eff_doserate, operator, zr_filter_id)
            )
        print("Finished inserting runs into the database.")

        results = self.exp_reader.query({
                    "tags": {
                        "dose": {"min": 0},
                    }
                })

        thresholds = [0, 2, 5] # in mJ/cm^2
        class __Week:
            def __init__(self):
                self.time = 0
                self.runs = np.zeros(len(thresholds), dtype=int) # total, over 2mj, over 5mj
                self.successes = np.zeros(len(thresholds), dtype=int) # total, over 2mj, over 5mj
                self.aborts = 0
                self.failures = np.zeros(len(thresholds), dtype=int) # total, over 2mj, over 5mj
                self.cumulative_dose = 0
                self.cumulative_runtime = 0

            def insert(self, conn):
                avg_doserate = float(self.cumulative_dose) / float(self.cumulative_runtime) if self.cumulative_runtime > 0 else 0
                print(f"Inserting weekly statistics for week starting {datetime.datetime.fromtimestamp(self.time)}: run_count={self.runs[0]}, success_count={self.successes[0]}, successes_over_2mj={self.successes[1]}, successes_over_5mj={self.successes[2]}, abort_count={self.aborts}, failure_count={self.failures[0]}, failures_over_2mj={self.failures[1]}, failures_over_5mj={self.failures[2]}, avg_doserate={avg_doserate}, cumulative_dose={self.cumulative_dose}, cumulative_runtime={self.cumulative_runtime}, runs_over_2mj={self.runs[1]}, runs_over_5mj={self.runs[2]}")
                
                conn.execute(
                    "INSERT INTO statistics_weekly (week_start, run_count, success_count, successes_over_2mj, successes_over_5mj, abort_count, failure_count, failures_over_2mj, failures_over_5mj, success_rate, success_rate_over_2mj, success_rate_over_5mj, avg_doserate, cumulative_dose, cumulative_runtime, runs_over_2mj, runs_over_5mj) VALUES (to_timestamp(%s), %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s);",
                    (self.time, self.runs[0], self.successes[0], self.successes[1], self.successes[2], self.aborts, self.failures[0], self.failures[1], self.failures[2], float(self.successes[0]) / self.runs[0] if self.runs[0] > 0 else 0, float(self.successes[1]) / self.runs[1] if self.runs[1] > 0 else 0, float(self.successes[2]) / self.runs[2] if self.runs[2] > 0 else 0, avg_doserate, self.cumulative_dose, self.cumulative_runtime, self.runs[1], self.runs[2])
                )

            def insert_thresholds(self, value, to_array, m_thresholds):
                #print(f"Checking thresholds for value: {value}, thresholds: {m_thresholds}")
                for i, threshold in enumerate(m_thresholds):
                    if float(value) > threshold:
                        to_array[i] += 1
                        #print(f"Value {value} exceeds threshold {threshold}, incrementing count, current counts: {to_array}")

        week = __Week()
        week.time = results[0].get_record().get_timestamp() // (7 * 24 * 60 * 60) * (7 * 24 * 60 * 60) # UNIX timestamp of the start of the week

        for result in results:
            res_week = result.get_record().get_timestamp() // (7 * 24 * 60 * 60) * (7 * 24 * 60 * 60)
            if res_week != week.time:
                week.insert(self.conn)

                week = __Week()
                week.time = res_week

            tags = result.get_tags()
            end_reason = tags.get("abort_reason")
            status = tags.get("status")

            week.cumulative_dose += float(tags.get("dose")) if tags.get("dose") is not None else 0
            week.cumulative_runtime += float(tags.get("runtime")) if tags.get("runtime") is not None else 0

            to_insert = week.failures
            if end_reason == USER_STOP_KEY:
                week.aborts += 1
                to_insert = None
            elif status == "STOPPED":
                to_insert = week.successes
            elif status == "ABORTED":
                to_insert = week.failures
            else:
                print(f"Unknown end_reason: {end_reason}, status: {status} for run: {result.get_name()}")
                to_insert = week.failures

            if to_insert is not None:
                week.insert_thresholds(float(tags.get("dose")) if tags.get("dose") is not None else 0, to_insert, thresholds)

            week.insert_thresholds(float(tags.get("dose")) if tags.get("dose") is not None else 0, week.runs, thresholds)
        
        # Insert the last week
        if week.runs[0] > 0:
            week.insert(self.conn)

        # Commit once everything has been inserted, to avoid partial updates in case of failure
        self.conn.commit()

if __name__ == "__main__":
    worker = DashboardWorker(SAVE_PATH, DB_URL)
    worker.repopulate()