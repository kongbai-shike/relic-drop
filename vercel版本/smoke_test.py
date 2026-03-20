from app_core import calculate_relic_ev


if __name__ == "__main__":
    result = calculate_relic_ev("Meso A6", refinement="radiant", status_filter="any", timeout_s=20.0)
    print(result["relic"], result["vault_status"], result["ev"])
    print("drops:", len(result["drops"]))

