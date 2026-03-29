
from ark_agentic.agents.securities.schemas import AccountOverviewSchema, ETFHoldingsSchema

def test_string_coercion():
    # Test case 1: Standard float string
    data = {
        "total_assets": "10000.50",
        "cash_balance": "5000.25",
        "stock_market_value": "4000.00",
        "today_profit": "150.50",
    }
    
    # Schema should preserve strings as strings
    schema = AccountOverviewSchema.model_validate(data)
    assert schema.total_assets == "10000.50"
    assert isinstance(schema.total_assets, str)
    
    print("String type preservation passed")

def test_precision_loss():
    # Test case 2: Precision check
    val_str = "0.123456789123456789"
    data = {
        "total_assets": val_str,
        "cash_balance": "0",
        "stock_market_value": "0",
        "today_profit": "0",
    }
    schema = AccountOverviewSchema.model_validate(data)
    
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
