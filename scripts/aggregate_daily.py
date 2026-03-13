from datetime import date
import argparse

from app.services.aggregation import aggregate_daily
from app.core.settings import Settings


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--ppm-max", type=float, default=None)
    args = ap.parse_args()

    settings = Settings.load()
    ppm_max = args.ppm_max or float(settings.nh3_ppm_max)

    aggregate_daily(
        date.fromisoformat(args.start),
        date.fromisoformat(args.end),
        ppm_max,
    )

    print("OK: agregação diária concluída.")


if __name__ == "__main__":
    main()