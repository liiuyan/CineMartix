#!/usr/bin/env python3
"""Preview Codex 搜索分流测试；全部使用假会话，不消耗真实搜索。"""

import unittest
from unittest.mock import Mock, patch

import config
from agents.preview_meta import PreviewMetaFetcher
from services.codex_runtime import CodexSearchTurn


class PreviewCodexSearchTests(unittest.TestCase):
    def _build_fetcher(self, search_turns):
        fake_session = Mock()
        fake_session.search_json.side_effect = search_turns
        fake_runtime = Mock()
        fake_runtime.create_preview_session.return_value = fake_session
        fake_brain = Mock()
        fake_brain.codex_runtime = fake_runtime

        with (
            patch.object(config.Strategy.System, "LLM_RUNTIME", "codex_sdk"),
            patch("agents.preview_meta.LLMBrain", return_value=fake_brain),
        ):
            fetcher = PreviewMetaFetcher()

        fetcher.serper_key = None
        fetcher._collect_serper_snippets = Mock(return_value=[])
        fetcher._fetch_with_gemini = Mock(
            side_effect=AssertionError("codex_sdk 模式不得调用 Gemini")
        )
        return fetcher, fake_session, fake_runtime

    def _movie(self):
        return {
            "name": "奥德赛",
            "path": "/tmp/odyssey.jpg",
            "index": 1,
            "lock_year": "2026",
            "lock_original_title": "The Odyssey",
            "movie_key": "奥德赛｜year｜2026",
        }

    def test_codex_search_overrides_conflict_and_records_sources(self):
        complete_data = {
            "original_title": "The Odyssey",
            "original_language": "en",
            "release_date": "2026-07-17",
            "release_region": "美国",
            "genres": "动作/奇幻/冒险",
            "region": "美国/英国",
            "director": "Christopher Nolan",
            "actors": "Matt Damon / Tom Holland",
            "overview": "奥德修斯在特洛伊战争后踏上漫长归乡旅程。",
            "sources": ["https://www.universalpictures.com/movies/the-odyssey"],
        }
        fetcher, session, _ = self._build_fetcher(
            [CodexSearchTurn(data=complete_data, web_search_used=True)]
        )
        fetcher._fetch_from_tmdb = Mock(
            return_value={
                "release_date": "2026-07-16",
                "tmdb_id": 1,
                "sources": ["https://www.themoviedb.org/movie/1"],
            }
        )
        fetcher._fetch_from_omdb = Mock(return_value={})
        fetcher._generate_hookline = Mock(return_value="诺兰实拍重塑荷马史诗")

        result = fetcher.collect_one(self._movie())

        self.assertEqual(result["release_date"], "2026-07-17")
        self.assertEqual(result["unconfirmed_fields"], [])
        self.assertIn(
            "https://www.universalpictures.com/movies/the-odyssey",
            result["sources"],
        )
        self.assertIn("https://www.themoviedb.org/movie/1", result["sources"])
        self.assertEqual(session.search_json.call_count, 1)
        self.assertEqual(
            fetcher._normalize_region_list("United Kingdom/United States of America"),
            "英国/美国",
        )
        self.assertEqual(fetcher._normalize_region_name("BE"), "比利时")
        fetcher._fetch_with_gemini.assert_not_called()

    def test_missing_required_facts_raise_after_three_search_rounds(self):
        empty_data = {
            "original_title": "",
            "original_language": "",
            "release_date": "",
            "release_region": "",
            "genres": "",
            "region": "",
            "director": "",
            "actors": "",
            "overview": "",
            "sources": ["https://example.com/movie"],
        }
        fetcher, session, _ = self._build_fetcher(
            [CodexSearchTurn(data=empty_data, web_search_used=True)] * 3
        )
        fetcher._fetch_from_tmdb = Mock(return_value={})
        fetcher._fetch_from_omdb = Mock(return_value={})
        fetcher._generate_hookline = Mock(return_value="")

        with self.assertRaisesRegex(
            ValueError,
            r"缺少必填字段: .*release_date.*overview",
        ):
            fetcher.collect_one(self._movie())

        self.assertEqual(session.search_json.call_count, 3)
        # 必填字段缺失时，必须先完成 Serper 后备再熔断。
        fetcher._collect_serper_snippets.assert_called_once()
        fetcher._fetch_with_gemini.assert_not_called()

    def test_results_without_native_web_event_are_not_accepted(self):
        apparently_complete = {
            "original_title": "The Odyssey",
            "original_language": "en",
            "release_date": "2026-07-17",
            "release_region": "美国",
            "genres": "冒险",
            "region": "美国",
            "director": "Christopher Nolan",
            "actors": "Matt Damon",
            "overview": "一段归乡冒险。",
            "sources": ["https://example.com/not-actually-searched"],
        }
        fetcher, session, _ = self._build_fetcher(
            [CodexSearchTurn(data=apparently_complete, web_search_used=False)] * 3
        )
        fetcher._fetch_from_tmdb = Mock(return_value={})
        fetcher._fetch_from_omdb = Mock(return_value={})
        fetcher._generate_hookline = Mock(return_value="")

        with self.assertRaisesRegex(ValueError, "release_date"):
            fetcher.collect_one(self._movie())

        self.assertEqual(session.search_json.call_count, 3)
        self.assertTrue(fetcher._domain_allowed("https://another-source.example/movie"))

    def test_optional_facts_are_retained_as_unconfirmed(self):
        required_only = {
            "original_title": "The Odyssey",
            "original_language": "en",
            "release_date": "2026-07-17",
            "release_region": "",
            "genres": "",
            "region": "",
            "director": "",
            "actors": "",
            "overview": "奥德修斯在特洛伊战争后踏上漫长归乡旅程。",
            "sources": ["https://example.com/movie"],
        }
        fetcher, session, _ = self._build_fetcher(
            [CodexSearchTurn(data=required_only, web_search_used=True)] * 3
        )
        fetcher._fetch_from_tmdb = Mock(return_value={})
        fetcher._fetch_from_omdb = Mock(return_value={})
        fetcher._generate_hookline = Mock(return_value="诺兰实拍重塑荷马史诗")

        result = fetcher.collect_one(self._movie())

        self.assertEqual(result["release_date"], "2026-07-17")
        self.assertIn("director", result["unconfirmed_fields"])
        self.assertIn("actors", result["unconfirmed_fields"])
        self.assertEqual(session.search_json.call_count, 3)

    def test_china_film_may_omit_original_title(self):
        china_film = {
            "original_title": "",
            "original_language": "zh",
            "release_date": "2026-08-01",
            "release_region": "中国",
            "genres": "剧情",
            "region": "中国",
            "director": "",
            "actors": "",
            "overview": "这是一部中文电影的剧情简介。",
            "sources": ["https://example.com/china-movie"],
        }
        fetcher, _, _ = self._build_fetcher(
            [CodexSearchTurn(data=china_film, web_search_used=True)] * 3
        )
        fetcher._fetch_from_tmdb = Mock(return_value={})
        fetcher._fetch_from_omdb = Mock(return_value={})
        fetcher._generate_hookline = Mock(return_value="新导演的现实主义新作")
        movie = self._movie()
        movie["lock_original_title"] = ""

        result = fetcher.collect_one(movie)

        self.assertTrue(result["is_china_film"])
        self.assertEqual(result["original_title"], "")

    def test_overview_may_be_empty_when_summary_block_is_disabled(self):
        no_overview = {
            "original_title": "The Odyssey",
            "original_language": "en",
            "release_date": "2026-07-17",
            "release_region": "",
            "genres": "",
            "region": "美国",
            "director": "",
            "actors": "",
            "overview": "",
            "sources": ["https://example.com/movie"],
        }
        fetcher, _, _ = self._build_fetcher(
            [CodexSearchTurn(data=no_overview, web_search_used=True)] * 3
        )
        fetcher.show_summary_block = False
        fetcher._fetch_from_tmdb = Mock(return_value={})
        fetcher._fetch_from_omdb = Mock(return_value={})
        fetcher._generate_hookline = Mock(return_value="诺兰实拍重塑荷马史诗")

        result = fetcher.collect_one(self._movie())

        self.assertEqual(result["overview"], "")
        self.assertIn("overview", result["unconfirmed_fields"])

    def test_cached_generated_fields_are_reused_but_live_search_still_runs(self):
        complete_data = {
            "original_title": "The Odyssey",
            "original_language": "en",
            "release_date": "2026-07-17",
            "release_region": "美国",
            "genres": "冒险",
            "region": "美国",
            "director": "Christopher Nolan",
            "actors": "Matt Damon",
            "overview": "奥德修斯踏上归乡旅程。",
            "sources": ["https://www.universalpictures.com/movies/the-odyssey"],
        }
        fetcher, session, _ = self._build_fetcher(
            [CodexSearchTurn(data=complete_data, web_search_used=True)]
        )
        fetcher._fetch_from_tmdb = Mock(return_value={})
        fetcher._fetch_from_omdb = Mock(return_value={})
        fetcher._generate_hookline = Mock(
            side_effect=AssertionError("缓存 hook 不应重复生成")
        )
        cached = {
            "hook": "诺兰实拍重塑荷马史诗",
            "summary": "这是一段已经完成并可复用的缓存简介。",
        }

        result = fetcher.collect_one(self._movie(), initial_data=cached)

        self.assertEqual(result["hook"], cached["hook"])
        self.assertEqual(result["summary"], cached["summary"])
        self.assertEqual(session.search_json.call_count, 1)
        fetcher._generate_hookline.assert_not_called()

    def test_api_mode_keeps_existing_gemini_fallback(self):
        fake_brain = Mock()
        with (
            patch.object(config.Strategy.System, "LLM_RUNTIME", "api"),
            patch("agents.preview_meta.LLMBrain", return_value=fake_brain),
        ):
            fetcher = PreviewMetaFetcher()

        fetcher.gemini_key = "test-gemini-key"
        fetcher.max_gemini_grounding = 1
        fetcher.gemini_hook_attempts = 0
        fetcher._fetch_from_tmdb = Mock(return_value={})
        fetcher._collect_serper_snippets = Mock(return_value=[])
        fetcher._fetch_with_gemini = Mock(
            return_value={
                "original_title": "The Odyssey",
                "release_date": "2026-07-17",
                "release_region": "美国",
                "genres": "冒险",
                "region": "美国",
                "director": "Christopher Nolan",
                "actors": "Matt Damon",
                "overview": "奥德修斯踏上归乡旅程。",
                "hook": "诺兰实拍重塑荷马史诗",
            }
        )
        fetcher._generate_hookline = Mock(
            side_effect=AssertionError("Gemini 已返回有效 hook，不应再次生成")
        )

        result = fetcher.collect_one(self._movie())

        self.assertEqual(result["release_date"], "2026-07-17")
        fetcher._fetch_with_gemini.assert_called_once()
        fetcher._generate_hookline.assert_not_called()


if __name__ == "__main__":
    unittest.main()
