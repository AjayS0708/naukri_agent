"""
Read-only utility to re-normalize salary_min/salary_max for existing jobs in DB.
This DOES NOT modify the database.

Usage (DO NOT RUN - FOR REVIEW ONLY):
  python -c "from backend.utils.salary_renormalize import generate_renormalization_sql; generate_renormalization_sql()"
"""

from backend.database.database import SessionLocal
from backend.models.job import Job
from backend.services.matching.normalizer import parse_salary_to_range
from sqlalchemy import select


def generate_renormalization_sql():
    """Generate SQL UPDATE statements for re-normalizing salary_min/salary_max from salary text."""
    session = SessionLocal()
    
    try:
        stmt = select(Job).where(Job.salary.isnot(None))
        jobs = session.execute(stmt).scalars().all()
        
        print("=" * 120)
        print("RE-NORMALIZATION REPORT")
        print("=" * 120)
        print(f"Total jobs with salary text: {len(jobs)}")
        print()
        
        update_count = 0
        updates = []
        
        for job in jobs:
            min_lpa, max_lpa = parse_salary_to_range(job.salary)
            needs_update = (job.salary_min != min_lpa) or (job.salary_max != max_lpa)
            
            if needs_update:
                update_count += 1
                sql = f"UPDATE jobs SET salary_min = {min_lpa}, salary_max = {max_lpa} WHERE id = {job.id};"
                updates.append(sql)
                
                if update_count <= 10:
                    print(f"Job ID {job.id}: '{job.salary}' -> ({min_lpa}, {max_lpa})")
                    print(f"  Current: ({job.salary_min}, {job.salary_max})")
                    print()
        
        print("=" * 120)
        print(f"Jobs needing update: {update_count}")
        print("=" * 120)
        print()
        print("To apply these updates, execute the following SQL (AFTER BACKUP):")
        print("=" * 120)
        print()
        
        if updates:
            for sql in updates:
                print(sql)
        else:
            print("-- No updates needed - all salary_min/max are already correct")
        
        print()
        print("=" * 120)
        
    finally:
        session.close()


if __name__ == "__main__":
    generate_renormalization_sql()
