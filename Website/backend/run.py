"""Application entrypoint.

Run from Website/backend:
    flask --app run:app run --debug
    # or
    python run.py
"""

from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
