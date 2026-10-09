"""Application entrypoint.

Run from Website/backend:
    flask --app run:app run --debug
    # or
    python run.py

Note: use_reloader=False so the exception-job worker is not killed mid-run
when a source file changes (Flask debug reloader would otherwise restart the
process and mark in-flight jobs as "interrupted").
"""

from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)
