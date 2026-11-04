from fastapi import FastAPI, UploadFile, File, Form, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, Column, Integer, String, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from datetime import datetime
import shutil
import os
from dotenv import load_dotenv
load_dotenv()
import time

# Import your pipeline
from src.exhibit_validator.pipeline import run_pipeline

# --- App Setup ---
app = FastAPI(title="Exhibit Validator API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Allow all origins for development. Restrict this in production.
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Database Setup (SQLite) ---
DATABASE_URL = "sqlite:///./validation_history.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class JobHistory(Base):
    __tablename__ = "jobs"
    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String, index=True)
    objective = Column(String)
    total = Column(Integer)
    ok_count = Column(Integer)
    suspicious_count = Column(Integer)
    wrong_count = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(bind=engine)

# Dependency to get DB session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# --- API Endpoints ---

@app.get("/api/history")
def get_history(db: Session = Depends(get_db)):
    """Retrieve the history of all validation jobs."""
    jobs = db.query(JobHistory).order_by(JobHistory.created_at.desc()).all()
    return jobs

@app.post("/api/validate")
async def validate_data(
    file: UploadFile = File(...),
    objective: str = Form(...),
    use_llm: bool = Form(True),
    db: Session = Depends(get_db)
):
    """Receive a file, run the validation pipeline, save history, and return results."""
    # 1. Save uploaded file temporarily
    temp_path = f"temp_{int(time.time())}_{file.filename}"
    with open(temp_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    try:
        # 2. Run the pipeline
        intent = {"objective": objective}
        result = run_pipeline(
            input_path=temp_path,
            intent=intent,
            taxonomy_path="configs/taxonomy.yaml",
            use_llm=use_llm
        )

        # 3. Save job history to database
        summary = result["summary"]
        job = JobHistory(
            filename=file.filename,
            objective=objective,
            total=summary["total"],
            ok_count=summary["ok"],
            suspicious_count=summary["suspicious"],
            wrong_count=summary["wrong"]
        )
        db.add(job)
        db.commit()
        
        return result

    finally:
        # 4. Cleanup temporary file
        if os.path.exists(temp_path):
            os.remove(temp_path)