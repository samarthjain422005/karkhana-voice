from apps.api.store import init_db, seed_synthetic_demo


def seed_aarav_pumps(today=None) -> None:
    seed_synthetic_demo(today)
    print("[seed_demo] Ensured synthetic Aarav Pumps dataset.")


if __name__ == "__main__":
    init_db()
    seed_aarav_pumps()
