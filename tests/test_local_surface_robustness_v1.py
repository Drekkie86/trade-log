from src.research.local_surface_robustness_v1 import _readiness,_bucket_spread,_bucket_seconds
def test_readiness():
 assert _readiness(1)=='INSUFFICIENT_FOR_CROSS_DATE'; assert _readiness(2)=='CROSS_DATE_DESCRIPTIVE_ONLY'; assert _readiness(5)=='EXPLORATORY_STABILITY_ONLY'; assert _readiness(20)=='READY_FOR_PREREGISTRATION_REVIEW_ONLY'
def test_buckets():
 assert _bucket_spread(None)=='MISSING'; assert _bucket_spread(.15)=='10_20'; assert _bucket_seconds(-4)=='1_5S'; assert _bucket_seconds(31)=='GT_30S'
