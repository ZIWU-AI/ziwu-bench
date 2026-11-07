"""Resolve a bounded, explicit model/harness matrix before credentials."""
import json
import os
from profiles import PROFILES


def matrix(profile="all", harness="all"):
    profiles = list(PROFILES) if profile == "all" else [profile]
    result = []
    for key in profiles:
        spec = PROFILES[key]
        for name in spec["harnesses"]:
            if harness in ("all", name): result.append({"profile": key, "harness": name})
    if not result: raise ValueError("No supported model/harness combination")
    return {"include": result}


if __name__ == "__main__":
    value = matrix(os.environ.get("MODEL_PROFILE", "all"), os.environ.get("HARNESS", "all"))
    with open(os.environ["GITHUB_OUTPUT"], "a") as output:
        output.write("model_matrix=" + json.dumps(value) + "\n")
