import argparse
import json

from app.config import Settings
from app.container import Container
from app.services.scenario_service import ScenarioService, scenarios


def _print_trace(result: dict) -> None:
    for step in result["trace"]:
        call = step["call"]
        print(f"\n{step['stage']} | LEAD {call['lead_id']} | CONSENT {call['consent_given']}")
        print(f"CURRENT/NEXT FIELD: {call['current_field']} | STATE: {call['status']}")
        print("EXTRACTED VALUE:", call["last_extraction"])
        print("VALIDATION:", call["last_validation"])
        for entry in call["transcript"][-2:]:
            print(f"{entry['role']}: {entry['text']}")
    if result["call"].escalation:
        print("ESCALATION / HANDOFF:", result["call"].escalation.model_dump_json(indent=2))
    if result["call"].completion_result:
        print("JOURNEY COMPLETED:", json.dumps(result["call"].completion_result, indent=2, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local synthetic Energy demo without live calls")
    parser.add_argument("--scripted", action="store_true", help="Run all demo scenarios")
    parser.add_argument("--scenario", help="Run one scenario by slug")
    parser.add_argument("--quiet", action="store_true", help="Only print the final status")
    args = parser.parse_args()

    settings = Settings.from_env()
    settings.llm_provider = settings.voice_provider = settings.dnc_provider = "mock"
    services = Container(settings)
    print("Synthetic demo only: no live phone calls, no audio saved, no real CIMET data.")

    try:
        available = scenarios()
        if args.scenario:
            selected = [args.scenario]
        elif args.scripted:
            selected = [item["scenario"] for item in available]
        else:
            for index, item in enumerate(available, 1):
                print(f"{index}. {item['title']}")
            number = int(input("Select scenario (1-9): "))
            if not 1 <= number <= len(available):
                raise ValueError("Select a scenario from 1 to 9")
            selected = [available[number - 1]["scenario"]]

        for name in selected:
            result = ScenarioService(services).run(name)
            if not args.quiet:
                _print_trace(result)
            call = result["call"]
            print(f"{name}: {'PASS' if result['passed'] else 'FAIL'} | {call.status}"
                  + (f" / {call.escalation.reason}" if call.escalation else ""))
            if not result["passed"]:
                raise AssertionError(f"Scenario failed: {name}")
    finally:
        services.db.close()


if __name__ == "__main__":
    main()
