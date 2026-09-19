from app.config import Settings
from app.container import Container


def main():
    services = Container(Settings.from_env())
    try:
        print(f"Seeded synthetic demo data: {len(services.db.list_leads())} leads in SQLite.")
        print("Existing leads and progress were preserved. All data is synthetic, not production CIMET data.")
    finally:
        services.db.close()


if __name__ == "__main__":
    main()
