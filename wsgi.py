import sys
import os

tramed_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tramed")
os.chdir(tramed_dir)
sys.path.insert(0, tramed_dir)

from app import app, db, scheduler

with app.app_context():
    db_path = os.path.join(app.instance_path, "tramed.db")
    if not os.path.exists(db_path):
        os.makedirs(app.instance_path, exist_ok=True)
        db.create_all()
        from seed_data import seed
        seed(app)

scheduler.init_app(app)
scheduler.start()
