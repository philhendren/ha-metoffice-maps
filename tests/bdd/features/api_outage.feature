Feature: Riding out a Met Office outage
  As a household that relies on the rain map
  I want Home Assistant to back off when the Met Office is struggling
  So that the forecast stays on screen and no requests are wasted

  Background:
    Given the forecast is showing the midnight run

  Scenario: Rate limiting doubles the wait, up to two hours, then recovers
    Given the Met Office answers every request with 429
    When the next check is due
    Then the next check is in 30 minutes
    When the next check is due
    Then the next check is in 60 minutes
    When the next check is due
    Then the next check is in 120 minutes
    When the next check is due
    Then the next check is in 120 minutes
    And the midnight run's frames stay on show
    Given the Met Office is working again
    When the next check is due
    Then the next check is in 15 minutes

  Scenario: A rejected key stops polling and asks for a new one
    Given the Met Office rejects the API key
    When the next check is due
    And four hours pass
    Then exactly 1 request is made
    And Home Assistant asks for a new API key
