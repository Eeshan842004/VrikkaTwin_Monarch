# Deploying the demo

The app needs no external services: models, reports, weather and the fictional personas are in the repository, and the
services layer runs in-process. Demo secrets have safe defaults; set real ones as environment variables in any
public deployment (`SECRET_KEY` of at least 32 characters, `AUDIT_KEY`, `FERNET_KEY` from `Fernet.generate_key()`,
and the `DEMO_*_PASSWORD` values; see `.env.example`).

## Local (recommended for judging)

```bash
cd Monarch_Vellore-Institute-of-Technology
.venv/Scripts/python -m streamlit run app/Home.py        # http://localhost:8501
```

## Docker

```bash
cd Monarch_Vellore-Institute-of-Technology
docker build -f docker/Dockerfile -t vrikkatwin .
docker run -p 7860:7860 vrikkatwin                       # http://localhost:7860
```

`docker/requirements-app.txt` is the runtime subset of `requirements.lock` (same pinned versions); it was checked by
running the Home, Doctor Triage, Patient Twin, Trust Center and Evaluation pages and the API health check in a fresh
virtual environment built from it. The image itself has not been built yet (Docker was not installed on the build
machine): build it once before relying on it.

## Hugging Face Spaces (Docker SDK)

1. Create a new Space (SDK: **Docker**, hardware: CPU basic is enough), owned by the team leader's account.
2. Copy the contents of `Monarch_Vellore-Institute-of-Technology/` into the Space repository root, and put this front
   matter at the top of the Space's `README.md`:

   ```yaml
   ---
   title: VrikkaTwin
   emoji: 🫘
   colorFrom: blue
   colorTo: green
   sdk: docker
   app_port: 7860
   dockerfile: docker/Dockerfile
   pinned: false
   ---
   ```

   (If your Spaces version ignores `dockerfile:`, copy `docker/Dockerfile` to the Space root and change its `COPY docker/`
   line to `COPY requirements-app.txt` after copying that file to the root too.)
3. In the Space settings, add the secrets listed above.
4. Push; the build takes a few minutes. Open the Space URL logged out to check it.

Fallback: Streamlit Community Cloud with `app/Home.py` as the entry point and `docker/requirements-app.txt` as the
requirements file (Python 3.12).

These steps need the team's own Hugging Face (or Streamlit) account, so they are not automated here.
