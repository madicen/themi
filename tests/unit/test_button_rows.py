from themi.channels.telegram import button_rows


def test_one_or_two_buttons_share_a_row() -> None:
    assert button_rows([]) == [[]]
    assert button_rows(["Go ahead"]) == [[0]]
    assert button_rows(["Done already", "Later today"]) == [[0, 1]]


def test_longer_labels_go_two_a_row() -> None:
    # Erin's idea #80: "For options with more text, maximum 2 buttons per line."
    assert button_rows(["Grocery list", "Things to Buy", "Not now"]) == [[0, 1], [2]]
    assert button_rows(["Urgent", "Time-sensitive", "No rush", "Stop for now"]) == [
        [0, 1],
        [2, 3],
    ]


def test_short_labels_go_three_a_row() -> None:
    # "If the options have short text (eg yes, no, ok, later) 3 options per line is ok."
    assert button_rows(["Yes", "No", "Later"]) == [[0, 1, 2]]
    assert button_rows(["Yes", "No", "Ok", "Later"]) == [[0, 1, 2], [3]]
