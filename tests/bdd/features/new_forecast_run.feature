Feature: Showing a new forecast run
  As someone glancing at the kitchen tablet
  I want the rain map to move to each new Met Office run
  So that the loop always shows the next six hours

  Background:
    Given the forecast is showing the midnight run

  Scenario: A new run arrives and six frames appear in order
    When a new run appears
    Then six frames are downloaded
    And the frames on show are valid at 11:00, 12:00, 13:00, 14:00, 15:00 and 16:00
    And the forecast sensor shows the 06:00 run

  Scenario: Nothing new costs one request
    When a quarter of an hour passes
    Then exactly 1 request is made
    And the midnight run's frames stay on show

  Scenario: A run that is still being published waits until it is complete
    When a new run appears with its 14:00 frame missing
    Then the midnight run's frames stay on show
    When the missing frame is published
    Then only the missing frames are downloaded
    And the forecast sensor shows the 06:00 run
