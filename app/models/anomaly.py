"""Anomaly Detection Model.

Stores detected anomalies in the database for tracking and analysis.
"""

from datetime import datetime

from sqlalchemy import JSON, Column, DateTime, Float, ForeignKey, Integer, String, Boolean
from sqlalchemy.orm import relationship

from app.db.base import Base


class Anomaly(Base):
    """Detected Anomaly Record.
    
    Stores results of anomaly detection for resources over time,
    enabling trend analysis and alert triggering.
    """

    __tablename__ = "anomalies"

    id = Column(Integer, primary_key=True, index=True)
    resource_id = Column(Integer, ForeignKey("resources.id"), nullable=False, index=True)
    
    # Detection results
    is_anomaly = Column(Boolean, nullable=False, default=False, index=True)
    confidence = Column(Float, nullable=False, default=0.0)  # 0-100
    anomaly_type = Column(String(50), nullable=False, index=True)  # isolation_forest, prophet, zombie, hybrid
    
    # Detection details
    isolation_forest_score = Column(Float, nullable=True)
    prophet_is_anomaly = Column(Boolean, nullable=True)
    prophet_confidence = Column(Float, nullable=True)
    zombie_is_idle = Column(Boolean, nullable=True)
    zombie_confidence = Column(Float, nullable=True)
    
    # Additional context
    cost_delta = Column(Float, nullable=True)
    cost_predicted = Column(Float, nullable=True)
    cost_actual = Column(Float, nullable=True)
    cpu_avg = Column(Float, nullable=True)
    efficiency_score = Column(Float, nullable=True)
    
    # Metadata
    details = Column(JSON, nullable=True)  # Full detection details
    recommendations = Column(JSON, nullable=True)  # List of action recommendations
    alert_sent = Column(Boolean, nullable=False, default=False)
    alert_sent_at = Column(DateTime, nullable=True)
    acknowledged = Column(Boolean, nullable=False, default=False)
    acknowledged_at = Column(DateTime, nullable=True)
    acknowledged_by = Column(String(255), nullable=True)
    notes = Column(String(1000), nullable=True)
    
    # Timestamps
    timestamp = Column(DateTime, nullable=False, index=True)
    detected_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    resource = relationship("Resource", back_populates="anomalies")
    
    def to_dict(self) -> dict:
        """Convert to dictionary.
        
        Returns:
            Dictionary representation
        """
        return {
            "id": self.id,
            "resource_id": self.resource_id,
            "is_anomaly": self.is_anomaly,
            "confidence": self.confidence,
            "anomaly_type": self.anomaly_type,
            "isolation_forest_score": self.isolation_forest_score,
            "prophet_is_anomaly": self.prophet_is_anomaly,
            "prophet_confidence": self.prophet_confidence,
            "zombie_is_idle": self.zombie_is_idle,
            "zombie_confidence": self.zombie_confidence,
            "cost_delta": self.cost_delta,
            "cost_predicted": self.cost_predicted,
            "cost_actual": self.cost_actual,
            "cpu_avg": self.cpu_avg,
            "efficiency_score": self.efficiency_score,
            "details": self.details,
            "recommendations": self.recommendations,
            "alert_sent": self.alert_sent,
            "acknowledged": self.acknowledged,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "detected_at": self.detected_at.isoformat() if self.detected_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
