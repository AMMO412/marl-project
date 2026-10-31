"""Compare domain-randomization manifests from multiple episodes."""

import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("manifests", nargs="+")
    parser.add_argument(
        "--output", default="runtime/acceptance/domain_randomization.json"
    )
    args = parser.parse_args()
    episodes = [json.loads(Path(path).read_text(encoding="utf-8")) for path in args.manifests]
    signatures = []
    for episode in episodes:
        signatures.append(
            [
                (
                    model["name"],
                    model["mass_scale"],
                    model["friction_mu"],
                    model["restitution_coefficient"],
                )
                for model in episode["models"]
            ]
        )
    report = {
        "episodes_checked": len(episodes),
        "episode_ids": [episode["episode_id"] for episode in episodes],
        "all_enabled": all(episode["enabled"] for episode in episodes),
        "models_per_episode": [len(episode["models"]) for episode in episodes],
        "unique_parameter_sets": len({json.dumps(item) for item in signatures}),
    }
    report["passed"] = (
        len(episodes) >= 3
        and report["all_enabled"]
        and all(count == 50 for count in report["models_per_episode"])
        and report["unique_parameter_sets"] == len(episodes)
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
