Fishing Knowledge Platform
DSCI 560 final project — a Flask web app for anglers, combining a community feed, a RAG-powered AI assistant, and a real-time fishing-condition forecaster for Southern California.
Features
Community — accounts, public feed, three group types (open / approval / invite-code), posts with images, comments, likes, notifications, in-group chat.
AI assistant — semantic search (sentence-transformers + FAISS) over posts, comments, and group messages, plus OpenAI gpt-4o-mini for grounded Q&A. Separate public and group-scoped assistants.
Fishing conditions — pulls hourly weather + marine data from Open-Meteo for 5 SoCal spots, scores each hour (wind / gust / wave / rain), and asks the LLM to recommend the best 2–3-hour window.
Tech Stack
Flask 3 · SQLAlchemy 2 · MySQL (PyMySQL) · sentence-transformers/all-MiniLM-L6-v2 · faiss-cpu · OpenAI SDK · Open-Meteo APIs
Structure
app.py              # routes, RAG pipeline, condition scoring

models.py           # SQLAlchemy models

templates/          # Jinja2 templates

static/uploads/     # post images

embedding_cache/    # FAISS indexes + metadata (auto-generated)

requirements.txt
Setup
git clone https://github.com/Skye-Zhu/dsci560-final.git

cd dsci560-final

python -m venv venv && source venv/bin/activate

pip install -r requirements.txt

Create the database and set your OpenAI key:

CREATE DATABASE fishing_platform CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

export OPENAI_API_KEY="sk-..."

Update the MySQL credentials at the top of app.py if needed, then run:

python app.py

App runs at http://localhost:8000. Tables and demo groups are auto-created on first launch. If you imported existing data, visit /rebuild_all_indexes once to build the FAISS indexes.
How It Works
RAG — query is encoded with MiniLM, searched against the matching FAISS index (score ≥ 0.35), with a keyword fallback. Retrieved snippets + bait/method/location stats are passed to gpt-4o-mini with strict grounding instructions. Indexes update incrementally on create/delete.

Condition score — each hour starts at 100 and loses points for high wind, gusts, waves, and rain probability, then is bucketed into Good / Moderate / Poor.
Team
DSCI 560 — Data Science Practicum, USC, Spring 2026.

