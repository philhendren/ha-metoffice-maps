Feature: Staying inside the daily request budget
  As a household on the Met Office free plan
  I want Home Assistant to stop asking for maps before the daily limit
  So that the forecast never costs more than the plan allows

  Background:
    Given the forecast is showing the midnight run
    And the daily cap is 800 requests

  Scenario: A new run that would cross the cap is skipped
    Given 795 requests have been made today
    When a new run appears
    Then no frames are downloaded
    And the midnight run's frames stay on show
    And 796 requests have been made today

  Scenario: At the cap, Home Assistant stops asking until midnight UTC
    Given 800 requests have been made today
    When an hour passes
    Then no requests are made
    And the requests sensor says the budget is exhausted
    And the midnight run's frames stay on show

  Scenario: The count starts again at midnight UTC
    Given 800 requests have been made today
    When the clock passes midnight UTC
    And a new run appears
    Then six frames are downloaded
