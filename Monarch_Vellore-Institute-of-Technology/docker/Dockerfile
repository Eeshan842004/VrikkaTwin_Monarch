# VrikkaTwin app image (Hugging Face Spaces, Docker SDK; also runs anywhere: docker run -p 7860:7860 vrikkatwin)
# Build from the team folder:  docker build -f docker/Dockerfile -t vrikkatwin .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    STREAMLIT_SERVER_HEADLESS=true STREAMLIT_BROWSER_GATHER_USAGE_STATS=false APP_MODE=inprocess

RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*
RUN useradd -m -u 1000 user
WORKDIR /home/user/app

COPY docker/requirements-app.txt /tmp/requirements-app.txt
RUN pip install -r /tmp/requirements-app.txt

COPY --chown=user pyproject.toml README.md LICENSE ./
COPY --chown=user src ./src
COPY --chown=user config ./config
COPY --chown=user app ./app
COPY --chown=user models ./models
COPY --chown=user reports ./reports
COPY --chown=user data/weather ./data/weather
COPY --chown=user data/synthetic/demo_patients.json ./data/synthetic/demo_patients.json
RUN pip install --no-deps -e .

USER user
# Pre-build the two reference heat-strain (ISO 7933 PHS) tables so the first page load is fast.
RUN python -c "from vrikka.physiology.exposure import reference_tables; reference_tables()"

EXPOSE 7860
CMD ["python", "-m", "streamlit", "run", "app/Home.py", "--server.port=7860", "--server.address=0.0.0.0"]
