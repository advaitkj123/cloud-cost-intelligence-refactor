"""Anomaly Repository - Data Access Layer for Anomalies."""

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from app.models.anomaly import Anomaly


class AnomalyRepository:
    """Repository for Anomaly CRUD operations and queries."""

    def __init__(self, db: Session):
        """Initialize repository.
        
        Args:
            db: Database session
        """
        self.db = db

    def create(self, anomaly: Anomaly) -> Anomaly:
        """Create new anomaly record.
        
        Args:
            anomaly: Anomaly model instance
            
        Returns:
            Created anomaly
        """
        self.db.add(anomaly)
        self.db.commit()
        self.db.refresh(anomaly)
        return anomaly

    def bulk_create(self, anomalies: list[Anomaly]) -> list[Anomaly]:
        """Create multiple anomaly records.
        
        Args:
            anomalies: List of Anomaly instances
            
        Returns:
            List of created anomalies
        """
        self.db.add_all(anomalies)
        self.db.commit()
        return anomalies

    def get_by_id(self, anomaly_id: int) -> Optional[Anomaly]:
        """Get anomaly by ID.
        
        Args:
            anomaly_id: Anomaly ID
            
        Returns:
            Anomaly or None
        """
        return self.db.query(Anomaly).filter(Anomaly.id == anomaly_id).first()

    def get_for_resource(self, resource_id: int, limit: int = 100) -> list[Anomaly]:
        """Get latest anomalies for resource.
        
        Args:
            resource_id: Resource ID
            limit: Maximum records to return
            
        Returns:
            List of anomalies ordered by timestamp desc
        """
        return (
            self.db.query(Anomaly)
            .filter(Anomaly.resource_id == resource_id)
            .order_by(desc(Anomaly.timestamp))
            .limit(limit)
            .all()
        )

    def get_anomalies_by_type(
        self, anomaly_type: str, limit: int = 100
    ) -> list[Anomaly]:
        """Get anomalies of specific type.
        
        Args:
            anomaly_type: Type of anomaly
            limit: Maximum records
            
        Returns:
            List of anomalies
        """
        return (
            self.db.query(Anomaly)
            .filter(Anomaly.anomaly_type == anomaly_type)
            .order_by(desc(Anomaly.detected_at))
            .limit(limit)
            .all()
        )

    def get_recent_anomalies(
        self, hours: int = 24, min_confidence: float = 50.0
    ) -> list[Anomaly]:
        """Get recent detected anomalies.
        
        Args:
            hours: Hours back to look
            min_confidence: Minimum confidence threshold
            
        Returns:
            List of anomalies
        """
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        return (
            self.db.query(Anomaly)
            .filter(
                Anomaly.is_anomaly == True,
                Anomaly.confidence >= min_confidence,
                Anomaly.detected_at >= cutoff,
            )
            .order_by(desc(Anomaly.detected_at))
            .all()
        )

    def get_unacknowledged(self, resource_id: Optional[int] = None) -> list[Anomaly]:
        """Get unacknowledged anomalies.
        
        Args:
            resource_id: Optional resource filter
            
        Returns:
            List of unacknowledged anomalies
        """
        query = (
            self.db.query(Anomaly)
            .filter(Anomaly.acknowledged == False)
            .order_by(desc(Anomaly.detected_at))
        )

        if resource_id:
            query = query.filter(Anomaly.resource_id == resource_id)

        return query.all()

    def acknowledge(
        self, anomaly_id: int, acknowledged_by: Optional[str] = None, notes: Optional[str] = None
    ) -> Anomaly:
        """Acknowledge anomaly.
        
        Args:
            anomaly_id: Anomaly ID
            acknowledged_by: User acknowledging
            notes: Optional notes
            
        Returns:
            Updated anomaly
        """
        anomaly = self.get_by_id(anomaly_id)
        if anomaly:
            anomaly.acknowledged = True
            anomaly.acknowledged_at = datetime.utcnow()
            anomaly.acknowledged_by = acknowledged_by
            anomaly.notes = notes
            self.db.commit()
            self.db.refresh(anomaly)
        return anomaly

    def mark_alert_sent(self, anomaly_id: int) -> Anomaly:
        """Mark alert as sent.
        
        Args:
            anomaly_id: Anomaly ID
            
        Returns:
            Updated anomaly
        """
        anomaly = self.get_by_id(anomaly_id)
        if anomaly:
            anomaly.alert_sent = True
            anomaly.alert_sent_at = datetime.utcnow()
            self.db.commit()
            self.db.refresh(anomaly)
        return anomaly

    def get_statistics(self, days: int = 30) -> dict:
        """Get anomaly statistics.
        
        Args:
            days: Days of history to analyze
            
        Returns:
            Statistics dict
        """
        cutoff = datetime.utcnow() - timedelta(days=days)

        total_anomalies = (
            self.db.query(func.count(Anomaly.id))
            .filter(Anomaly.detected_at >= cutoff)
            .scalar()
        )

        by_type = (
            self.db.query(Anomaly.anomaly_type, func.count(Anomaly.id))
            .filter(Anomaly.detected_at >= cutoff)
            .group_by(Anomaly.anomaly_type)
            .all()
        )

        avg_confidence = (
            self.db.query(func.avg(Anomaly.confidence))
            .filter(Anomaly.is_anomaly == True, Anomaly.detected_at >= cutoff)
            .scalar()
        )

        resources_with_anomalies = (
            self.db.query(func.count(func.distinct(Anomaly.resource_id)))
            .filter(Anomaly.is_anomaly == True, Anomaly.detected_at >= cutoff)
            .scalar()
        )

        acknowledged_count = (
            self.db.query(func.count(Anomaly.id))
            .filter(Anomaly.acknowledged == True, Anomaly.detected_at >= cutoff)
            .scalar()
        )

        return {
            "period_days": days,
            "total_anomalies": total_anomalies or 0,
            "anomalies_by_type": dict(by_type) if by_type else {},
            "avg_confidence": float(avg_confidence or 0.0),
            "resources_with_anomalies": resources_with_anomalies or 0,
            "acknowledged_count": acknowledged_count or 0,
            "unacknowledged_count": (total_anomalies or 0) - (acknowledged_count or 0),
        }

    def delete_older_than(self, days: int = 90) -> int:
        """Delete anomaly records older than specified days.
        
        Args:
            days: Delete records older than this many days
            
        Returns:
            Number of records deleted
        """
        cutoff = datetime.utcnow() - timedelta(days=days)
        count = (
            self.db.query(Anomaly)
            .filter(Anomaly.created_at < cutoff)
            .delete()
        )
        self.db.commit()
        return count
