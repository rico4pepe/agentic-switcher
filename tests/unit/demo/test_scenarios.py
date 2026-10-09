"""Tests for demo scenario control mechanism."""

from switcher.demo.scenarios import (
    DemoScenarioConfig,
    DemoScenarioName,
    get_demo_scenario,
    get_demo_scenario_config,
    reset_demo_scenario,
    set_demo_scenario,
)


def test_normal_scenario_can_be_selected():
    reset_demo_scenario()
    config = set_demo_scenario(DemoScenarioName.NORMAL)
    assert config.scenario == DemoScenarioName.NORMAL
    assert config.vendor_a_available is True
    assert config.vendor_b_available is True


def test_vendor_a_unavailable_makes_a_unavailable_while_b_remains_eligible():
    reset_demo_scenario()
    config = set_demo_scenario(DemoScenarioName.VENDOR_A_UNAVAILABLE)
    assert config.vendor_a_available is False
    assert config.vendor_b_available is True
    assert get_demo_scenario() == DemoScenarioName.VENDOR_A_UNAVAILABLE


def test_policy_denied_produces_insufficient_account_condition():
    reset_demo_scenario()
    config = set_demo_scenario(DemoScenarioName.POLICY_DENIED)
    assert config.account_balance_override == 0.0
    assert config.scenario == DemoScenarioName.POLICY_DENIED


def test_timeout_configures_vendor_simulation_to_produce_timeout_behavior():
    reset_demo_scenario()
    config = set_demo_scenario(DemoScenarioName.TIMEOUT)
    assert config.vendor_simulation.vendor_a_timeout is True


def test_planner_a_a_unavailable_scenario():
    reset_demo_scenario()
    config = set_demo_scenario(DemoScenarioName.PLANNER_A_A_UNAVAILABLE)
    assert config.scenario == DemoScenarioName.PLANNER_A_A_UNAVAILABLE
    assert config.vendor_a_available is False
    assert config.vendor_b_available is True


def test_normal_reset_restores_conditions():
    set_demo_scenario(DemoScenarioName.VENDOR_A_UNAVAILABLE)
    set_demo_scenario(DemoScenarioName.POLICY_DENIED)
    reset_demo_scenario()
    config = get_demo_scenario_config()
    assert config.scenario == DemoScenarioName.NORMAL
    assert config.vendor_a_available is True
    assert config.vendor_b_available is True
    assert config.account_balance_override is None


def test_unknown_scenario_names_are_rejected():
    import pytest

    from switcher.demo.scenarios import set_demo_scenario

    with pytest.raises(ValueError):
        set_demo_scenario("INVALID_SCENARIO")  # type: ignore


def test_scenario_selection_does_not_execute_transaction():
    # Just setting scenarios shouldn't have side effects
    reset_demo_scenario()
    initial_scenario = get_demo_scenario()
    set_demo_scenario(DemoScenarioName.TIMEOUT)
    assert get_demo_scenario() == DemoScenarioName.TIMEOUT
    assert initial_scenario == DemoScenarioName.NORMAL
