"""
Example script demonstrating the ingestion pipeline.

This script shows how to:
1. Initialize the ingestion service
2. Run collection manually
3. Check results
4. Schedule periodic collection
"""

import sys
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, str(__file__).rsplit("\\", 2)[0])

from app.db.session import SessionLocal
from app.services.ingestion_service import IngestionService
from app.ingestion.scheduler import IngestionScheduler
from app.core.logger import logger, setup_logging


def main():
    """Run example ingestion pipeline."""
    setup_logging()
    
    print("\n" + "=" * 70)
    print("  Cloud Ingestion Pipeline Example")
    print("=" * 70 + "\n")

    db = SessionLocal()
    try:
        # Initialize ingestion service
        print("[1] Initializing ingestion service...")
        ingestion_service = IngestionService(db)
        print("    ✓ Ingestion service initialized\n")

        # Run single cycle
        print("[2] Running single ingestion cycle for us-east-1...")
        print("-" * 70)
        results = ingestion_service.ingest_region("us-east-1")
        print("-" * 70)
        print(f"    ✓ Cycle completed at {results['timestamp']}")
        print(f"    • Metrics collected: {results['total_metrics_collected']}")
        print(f"    • Resources created: {results['resources_created']}")
        print(f"    • Resources updated: {results['resources_updated']}")
        print(f"    • Metrics stored: {results['metrics_stored']}")
        
        if results["errors"]:
            print(f"    • Errors encountered: {len(results['errors'])}")
            for error in results["errors"]:
                print(f"      - {error}")
        else:
            print("    • No errors\n")

        # Demonstrate multiple regions
        print("[3] Running cycle for multiple regions...")
        print("-" * 70)
        results_multi = ingestion_service.ingest_all_regions(["us-east-1", "us-west-2"])
        print("-" * 70)
        print(f"    ✓ Multi-region cycle completed")
        print(f"    • Total metrics: {results_multi['total_metrics_collected']}")
        print(f"    • Total stored: {results_multi['metrics_stored']}\n")

        # Demonstrate scheduler
        print("[4] Demonstrating scheduler setup...")
        scheduler = IngestionScheduler()
        
        # Create a simple collection function
        def collection_job():
            logger.info("Scheduled collection job running...")
            cycle_results = ingestion_service.run_ingestion_cycle()
            logger.info(f"Scheduled cycle results: {cycle_results}")
        
        # Add job to scheduler
        scheduler.add_job(
            collection_job,
            interval_minutes=5,
            job_id="example-ingestion"
        )
        
        # Show scheduled jobs
        jobs = scheduler.get_jobs()
        print(f"    ✓ Scheduler configured with {len(jobs)} job(s)")
        for job in jobs:
            print(f"      - Job: {job['name']}")
            print(f"        ID: {job['id']}")
            print(f"        Next run: {job['next_run_time']}\n")

        # Start scheduler (optional - just for demo)
        print("[5] Starting scheduler (demo mode - will stop after 10 seconds)...")
        scheduler.start()
        print(f"    ✓ Scheduler started at {datetime.now()}")
        print(f"    • Status: {'Running' if scheduler.is_running() else 'Stopped'}\n")

        # In production, you would let this run
        # For demo, we'll stop it after a few seconds
        import time
        time.sleep(3)
        scheduler.stop()
        print(f"    ✓ Scheduler stopped at {datetime.now()}\n")

        # Print summary
        print("=" * 70)
        print("  Example Summary")
        print("=" * 70)
        print("""
✓ Successfully demonstrated:
  1. Ingestion service initialization
  2. Single region collection
  3. Multi-region collection
  4. Scheduler configuration and startup
  5. Error handling and result tracking

Next steps:
  1. Configure AWS credentials in .env
  2. Set CLOUD_COLLECTOR_MODE=aws
  3. Start the FastAPI application
  4. The ingestion cycle will run automatically every 5 minutes
  5. Or trigger manually via POST /ingestion/trigger

For more information, see:
  - app/ingestion/README.md
  - app/services/ingestion_service.py
  - app/ingestion/aws_collector.py
        """)
        print("=" * 70 + "\n")

    except Exception as e:
        logger.error(f"Error in example: {e}", exc_info=True)
        print(f"\n✗ Error: {e}\n")
    finally:
        db.close()


if __name__ == "__main__":
    main()
