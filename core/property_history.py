"""Persistent audit records for property modelling runs."""
from copy import deepcopy
from datetime import datetime, timezone
from .props import grid_hash


def record(project, name, settings, outputs, status="Completed", message="", job_id=None):
    if status == "Completed" and job_id is None:
        from .property_workflow import job_from_history
        job = job_from_history(name, settings, outputs, project.property_jobs)
        if job is not None:
            project.property_jobs.append(job)
            job_id = job["id"]
    project.property_history.append(dict(
        time=datetime.now(timezone.utc).isoformat(), name=name, status=status,
        outputs=list(outputs), settings=deepcopy(settings), message=str(message), job_id=job_id,
        grid_hash=grid_hash(project.grid) if project.grid is not None else None, crs=deepcopy(project.crs)))
