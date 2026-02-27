
from ark_agentic.agents.securities.schemas import AccountOverviewSchema, ETFHoldingsSchema

def test_string_coercion():
    # Test case 1: Standard float string
    data = {
        "totalAssets": "10000.50",
        "cashBalance": "5000.25",
        "stockValue": "4000.00",
        "todayProfit": "150.50",
        "totalProfit": "2000.00",
        "profitRate": "0.15",
        "updateTime": "2024-01-01"
    }
    
    # Schema should preserve strings as strings
    schema = AccountOverviewSchema.from_raw_data(data)
    assert schema.total_assets == "10000.50"
    assert isinstance(schema.total_assets, str)
    
    print("String type preservation passed")

def test_precision_loss():
    # Test case 2: Precision check
    # We want to ensure that if we pass a high-precision string, it is NOT converted to float and back
    val_str = "0.123456789123456789"
    data = {
        "totalAssets": val_str,
        "cashBalance": "0", "stockValue": "0", "todayProfit": "0", 
        "totalProfit": "0", "profitRate": "0", "updateTime": "now"
    }
    schema = AccountOverviewSchema.from_raw_data(data)
    
    # Should be exact match
    print(f"Original: {val_str}")
    print(f"Schema:   {schema.total_assets}")
    
    assert schema.total_assets == val_str
    print("Precision check passed (Exact match)")

if __name__ == "__main__":
    try:
        test_string_coercion()
        test_precision_loss()
        print("ALL TESTS PASSED")
    except Exception as e:
        print(f"TEST FAILED: {e}")
        raise
