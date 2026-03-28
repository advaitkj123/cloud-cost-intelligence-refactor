from __future__ import annotations

import json
from functools import lru_cache

from botocore.exceptions import BotoCoreError, ClientError

from app.cloud.aws.client import AWSClientFactory, get_aws_client_factory
from app.core.config import get_settings

settings = get_settings()

AWS_REGION_TO_LOCATION = {
    "us-east-1": "US East (N. Virginia)",
    "us-east-2": "US East (Ohio)",
    "us-west-1": "US West (N. California)",
    "us-west-2": "US West (Oregon)",
    "eu-west-1": "EU (Ireland)",
    "eu-west-2": "EU (London)",
    "eu-west-3": "EU (Paris)",
    "eu-central-1": "EU (Frankfurt)",
    "eu-central-2": "Europe (Zurich)",
    "eu-north-1": "EU (Stockholm)",
    "ap-south-1": "Asia Pacific (Mumbai)",
    "ap-south-2": "Asia Pacific (Hyderabad)",
    "ap-southeast-1": "Asia Pacific (Singapore)",
    "ap-southeast-2": "Asia Pacific (Sydney)",
    "ap-southeast-3": "Asia Pacific (Jakarta)",
    "ap-southeast-4": "Asia Pacific (Melbourne)",
    "ap-northeast-1": "Asia Pacific (Tokyo)",
    "ap-northeast-2": "Asia Pacific (Seoul)",
    "ap-northeast-3": "Asia Pacific (Osaka)",
    "ca-central-1": "Canada (Central)",
    "sa-east-1": "South America (Sao Paulo)",
}

STATIC_EC2_PRICING = {
    "t2.micro": 0.0116,
    "t3.micro": 0.0104,
    "t3.small": 0.0208,
    "t3.medium": 0.0416,
    "t3.large": 0.0832,
    "t3.xlarge": 0.1664,
    "m5.large": 0.096,
    "m5.xlarge": 0.192,
    "c5.large": 0.085,
    "c5.xlarge": 0.17,
}


class AWSPricingService:
    def __init__(self, client_factory: AWSClientFactory | None = None) -> None:
        self.client_factory = client_factory or get_aws_client_factory()

    @lru_cache(maxsize=256)
    def get_ec2_hourly_price(self, instance_type: str, region_name: str) -> float:
        if not settings.aws_use_pricing_api:
            return STATIC_EC2_PRICING.get(instance_type, settings.ec2_hourly_rate)

        location = AWS_REGION_TO_LOCATION.get(region_name)
        if not location:
            return STATIC_EC2_PRICING.get(instance_type, settings.ec2_hourly_rate)

        client = self.client_factory.pricing()
        try:
            response = client.get_products(
                ServiceCode="AmazonEC2",
                Filters=[
                    {"Type": "TERM_MATCH", "Field": "instanceType", "Value": instance_type},
                    {"Type": "TERM_MATCH", "Field": "location", "Value": location},
                    {"Type": "TERM_MATCH", "Field": "operatingSystem", "Value": "Linux"},
                    {"Type": "TERM_MATCH", "Field": "preInstalledSw", "Value": "NA"},
                    {"Type": "TERM_MATCH", "Field": "capacitystatus", "Value": "Used"},
                    {"Type": "TERM_MATCH", "Field": "tenancy", "Value": "Shared"},
                ],
                MaxResults=20,
            )
        except (ClientError, BotoCoreError):
            return STATIC_EC2_PRICING.get(instance_type, settings.ec2_hourly_rate)

        for price_item in response.get("PriceList", []):
            price_document = json.loads(price_item)
            for term in price_document.get("terms", {}).get("OnDemand", {}).values():
                for price_dimension in term.get("priceDimensions", {}).values():
                    price_per_unit = price_dimension.get("pricePerUnit", {}).get("USD")
                    if price_per_unit:
                        return float(price_per_unit)

        return STATIC_EC2_PRICING.get(instance_type, settings.ec2_hourly_rate)

    def estimate_cost(self, cost_per_hour: float, usage_hours: float) -> float:
        return round(cost_per_hour * max(usage_hours, 0.0), 6)
