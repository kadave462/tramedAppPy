import sys
import importlib

REQUIRED = [
    ("flask",             "Flask"),
    ("flask_sqlalchemy",  "Flask-SQLAlchemy"),
    ("flask_apscheduler", "Flask-APScheduler"),
    ("sqlalchemy",        "SQLAlchemy"),
    ("dotenv",            "python-dotenv"),
    ("numpy",             "numpy"),
    ("pandas",            "pandas"),
    ("anthropic",         "anthropic"),
    ("twilio",            "twilio"),
]

def check():
    missing = []
    for module, package in REQUIRED:
        try:
            importlib.import_module(module)
        except ImportError:
            missing.append(package)

    if missing:
        print("\n❌ Missing packages — run this to fix:\n")
        print(f"  .venv\\Scripts\\pip install {' '.join(missing)}\n")
        sys.exit(1)

    print("✅ All packages present — starting app...\n")

if __name__ == "__main__":
    check()
    import os
    tramed_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tramed")
    os.chdir(tramed_dir)
    sys.path.insert(0, tramed_dir)
    from app import app, scheduler, db
    db_path = os.path.join(app.instance_path, "tramed.db")
    with app.app_context():
        if not os.path.exists(db_path):
            os.makedirs(app.instance_path, exist_ok=True)
            db.create_all()
            from seed_data import seed
            seed(app)
    scheduler.init_app(app)
    scheduler.start()
    app.run(debug=True, port=5000, use_reloader=False)