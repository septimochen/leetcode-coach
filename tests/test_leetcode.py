from leetcode_coach.leetcode import LeetCodeClient


def test_converts_graphql_problem_shape() -> None:
    problems = LeetCodeClient._problems([{"title": "Two Sum", "titleSlug": "two-sum", "questionFrontendId": "1", "difficulty": "Easy", "acRate": 55.3, "topicTags": [{"name": "Array"}, {"name": "Hash Table"}]}])
    assert problems[0].title_slug == "two-sum"
    assert problems[0].frontend_id == "1"
    assert problems[0].topic_tags == ["Array", "Hash Table"]
    assert problems[0].url == "https://leetcode.com/problems/two-sum/"
