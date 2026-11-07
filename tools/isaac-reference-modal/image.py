"""Isaac 6 image derivation from PR #2195's pinned Modal engine image.

The public task Dockerfiles offer the independent NGC rebuild. This path uses
its tested Python 3.12 / Isaac 6 engine cache, then removes inherited task code
and installs only the selected hash-checked task. Never includes /solution.
"""
from pathlib import Path
import modal

BASE_IMAGE = "im-VbjOSj3gdypwNyoZQA58DH"
ENGINE = "6.0.1.0"
IGNORE = ["**/__pycache__/**", "**/*.pyc"]


def image_for(directory):
    directory = Path(directory)
    dockerfile = (directory / "Dockerfile").read_text()
    # Only the engine provisioning prefix differs from the public NGC build.
    task_steps = dockerfile[dockerfile.index("COPY runtime-requirements.txt"):]
    commands = [line.strip() for line in task_steps.replace("\\\n", " ").splitlines()
                if line.strip() and not line.lstrip().startswith("#")]
    image = modal.Image.from_id(BASE_IMAGE).dockerfile_commands(
        "USER root",
        "RUN rm -rf /workspace/RoboDojo /workspace/anchor_merged /workspace/anchor_runs /opt/physicalrsi /opt/robodojo /solution /tests /app /opt/pen-runtime /root/autodl-tmp/LXC/RoboDojo && chmod 700 /root",
        "RUN test ! -e /opt/venv && ln -s /workspace/miniconda3/envs/RoboDojo /opt/venv",
        "ENV PATH=/opt/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin PYTHONPATH= PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 ACCEPT_EULA=Y OMNI_KIT_ACCEPT_EULA=YES PRIVACY_CONSENT=Y NVIDIA_DRIVER_CAPABILITIES=all",
        "RUN apt-get update && apt-get install -y --no-install-recommends sudo ffmpeg && rm -rf /var/lib/apt/lists/*",
    )
    return image.dockerfile_commands(commands, context_dir=directory, ignore=IGNORE)
