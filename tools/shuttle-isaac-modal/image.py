"""Reviewed Isaac 6 cache; task code executes only inside the GPU sandbox."""
from pathlib import Path
import modal
BASE_IMAGE = 'im-VbjOSj3gdypwNyoZQA58DH'
PYTHON = '/workspace/miniconda3/envs/RoboDojo/bin/python'

def image_for(directory):
    directory = Path(directory)
    text = (directory / 'Dockerfile').read_text()
    steps = text[text.index('COPY requirements.txt'):]
    commands = [s.strip() for s in steps.replace('\\\n', ' ').splitlines()
                if s.strip() and not s.lstrip().startswith('#')]
    base = modal.Image.from_id(BASE_IMAGE).dockerfile_commands(
        'USER root',
        'RUN rm -rf /workspace/RoboDojo /workspace/anchor_merged /workspace/anchor_runs /opt/physicalrsi /opt/robodojo /solution /tests /app /opt/pen-runtime /root/autodl-tmp/LXC/RoboDojo && chmod 700 /root',
        'RUN test ! -e /opt/venv && ln -s /workspace/miniconda3/envs/RoboDojo /opt/venv',
        'ENV PATH=/opt/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin PYTHONPATH= PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 ACCEPT_EULA=Y OMNI_KIT_ACCEPT_EULA=YES PRIVACY_CONSENT=Y NVIDIA_DRIVER_CAPABILITIES=all OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1',
        'RUN apt-get update && apt-get install -y --no-install-recommends libseccomp2 libegl1 libx11-xcb1 libxss1 libxtst6 git curl ca-certificates && rm -rf /var/lib/apt/lists/*')
    return base.dockerfile_commands(commands, context_dir=directory, ignore=['**/__pycache__/**','**/*.pyc'])
