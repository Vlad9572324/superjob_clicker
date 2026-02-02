"""
Авторизация и API superjob.ru
"""

import requests
import uuid
import json
import os
from datetime import datetime, timezone
from typing import Optional, List


def load_env(filepath: str) -> dict:
    """Загрузка .env файла"""
    env = {}
    if not os.path.exists(filepath):
        return env
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            # Обработка \n в значениях
            value = value.replace("\\n", "\n")
            env[key.strip()] = value.strip()
    return env


class SuperjobConfig:
    """Конфигурация из .env"""

    def __init__(self, env_path: str = None):
        if env_path is None:
            env_path = os.path.join(os.path.dirname(__file__), ".env")
        env = load_env(env_path)

        self.browser = env.get("BROWSER", "auto")
        self.resume_id = env.get("RESUME_ID", "")
        self.search_keywords = [k.strip() for k in env.get("SEARCH_KEYWORDS", "").split(",") if k.strip()]
        self.search_limit = int(env.get("SEARCH_LIMIT", "20"))
        self.max_pages = int(env.get("MAX_PAGES", "1"))
        self.cover_letter = env.get("COVER_LETTER", "")


class SuperjobAPI:
    """Класс для работы с superjob.ru API через куки"""

    BASE_URL = "https://www.superjob.ru"
    API_URL = "https://www.superjob.ru/jsapi3/0.1"
    COOKIES_CACHE_FILE = os.path.join(os.path.dirname(__file__), ".superjob_cookies.json")

    def __init__(self):
        self.config = SuperjobConfig()
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36",
            "Accept": "application/json",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
            "Content-Type": "application/json",
            "X-Frontend-Project": "desktop",
            "X-Requested-With": "XMLHttpRequest",
            "X-Subdomain": "www",
        })

    def auth_with_cookies(
        self,
        uat: str,
        sat: str,
        sask: str,
        geo: str = "1687",
        geo_confirmed: str = "1",
        geo_set: str = "1",
        login_auth_type: str = "applicant"
    ) -> bool:
        """
        Авторизация через куки

        Args:
            uat: токен авторизации пользователя
            sat: токен сессии
            sask: ключ сессии
            geo: ID региона (1687 = Москва)
            geo_confirmed: подтверждение региона
            geo_set: установка региона
            login_auth_type: тип авторизации (applicant/employer)

        Returns:
            bool: успешность авторизации
        """
        cookies = {
            "uat": uat,
            "sat": sat,
            "sask": sask,
            "geo": geo,
            "geoConfirmed": geo_confirmed,
            "geoSet": geo_set,
            "loginAuthType": login_auth_type,
            "initialGeoConfirmationShow": "1",
        }

        for name, value in cookies.items():
            self.session.cookies.set(name, value, domain=".superjob.ru", path="/")

        return self.check_auth()

    def _load_cached_cookies(self) -> Optional[dict]:
        """Загрузка кук из кеша"""
        try:
            if os.path.exists(self.COOKIES_CACHE_FILE):
                with open(self.COOKIES_CACHE_FILE, "r") as f:
                    return json.load(f)
        except Exception:
            pass
        return None

    def _save_cookies_to_cache(self, cookies: dict) -> None:
        """Сохранение кук в кеш"""
        try:
            with open(self.COOKIES_CACHE_FILE, "w") as f:
                json.dump(cookies, f)
        except Exception:
            pass

    def _auth_with_cached_cookies(self) -> bool:
        """Попытка авторизации через кешированные куки"""
        cached = self._load_cached_cookies()
        if not cached:
            return False

        required = ["uat", "sat", "sask"]
        if not all(k in cached for k in required):
            return False

        result = self.auth_with_cookies(
            uat=cached.get("uat"),
            sat=cached.get("sat"),
            sask=cached.get("sask"),
            geo=cached.get("geo", "1687"),
            geo_confirmed=cached.get("geoConfirmed", "1"),
            geo_set=cached.get("geoSet", "1"),
            login_auth_type=cached.get("loginAuthType", "applicant"),
        )
        return result

    def auth_from_browser(self, browser: str = "auto", force_refresh: bool = False) -> bool:
        """
        Автоматическое извлечение куки из браузера с кешированием

        Args:
            browser: браузер (auto, chrome, firefox, edge, safari)
                     auto = пробует все браузеры по очереди
            force_refresh: принудительно обновить куки из браузера

        Returns:
            bool: успешность авторизации

        Требуется: pip install browser_cookie3
        """
        # Сначала пробуем кешированные куки
        if not force_refresh:
            print("🔄 Проверяю кеш...", end=" ", flush=True)
            if self._auth_with_cached_cookies():
                print("✅ куки валидны")
                return True
            print("❌ кеш пуст или невалиден")

        # Если кеш не сработал - грузим из браузера
        try:
            import browser_cookie3
        except ImportError:
            raise ImportError("Установите browser_cookie3: pip install browser_cookie3")

        browser_funcs = {
            "chrome": browser_cookie3.chrome,
            "firefox": browser_cookie3.firefox,
            "edge": browser_cookie3.edge,
            "safari": browser_cookie3.safari,
        }

        # Порядок для auto: firefox стабильнее, потом chrome
        if browser == "auto":
            browsers_to_try = ["firefox", "chrome", "edge", "safari"]
        else:
            if browser not in browser_funcs:
                raise ValueError(f"Неизвестный браузер: {browser}. Доступны: {list(browser_funcs.keys())}")
            browsers_to_try = [browser]

        last_error = None
        for br in browsers_to_try:
            print(f"🔄 Пробую {br}...", end=" ", flush=True)
            try:
                cj = browser_funcs[br](domain_name=".superjob.ru")

                cookies = {}
                for cookie in cj:
                    cookies[cookie.name] = cookie.value

                required = ["uat", "sat", "sask"]
                missing = [k for k in required if k not in cookies]
                if missing:
                    last_error = f"[{br}] Не найдены куки: {missing}"
                    continue

                result = self.auth_with_cookies(
                    uat=cookies.get("uat"),
                    sat=cookies.get("sat"),
                    sask=cookies.get("sask"),
                    geo=cookies.get("geo", "1687"),
                    geo_confirmed=cookies.get("geoConfirmed", "1"),
                    geo_set=cookies.get("geoSet", "1"),
                    login_auth_type=cookies.get("loginAuthType", "applicant"),
                )

                if result:
                    print("✅")
                    self._save_cookies_to_cache(cookies)
                    return True
                else:
                    print("❌ невалидны")
                    last_error = f"[{br}] Куки невалидны"

            except Exception as e:
                print(f"❌ {e}")
                last_error = f"[{br}] {e}"
                continue

        if last_error:
            print(f"⚠️ Ошибка извлечения кук: {last_error}")
        return False

    def auth_from_file(self, filepath: str = "cookies.txt") -> bool:
        """
        Авторизация из файла с куки (формат: name=value, по одной на строку)
        """
        cookies = {}
        with open(filepath, "r") as f:
            for line in f:
                line = line.strip()
                if line and "=" in line:
                    name, value = line.split("=", 1)
                    cookies[name.strip()] = value.strip()

        required = ["uat", "sat", "sask"]
        missing = [k for k in required if k not in cookies]
        if missing:
            raise ValueError(f"Отсутствуют обязательные куки: {missing}")

        # Маппинг имён куки из файла в параметры функции
        return self.auth_with_cookies(
            uat=cookies.get("uat"),
            sat=cookies.get("sat"),
            sask=cookies.get("sask"),
            geo=cookies.get("geo", "1687"),
            geo_confirmed=cookies.get("geoConfirmed", "1"),
            geo_set=cookies.get("geoSet", "1"),
            login_auth_type=cookies.get("loginAuthType", "applicant"),
        )

    def check_auth(self) -> bool:
        """Проверка авторизации"""
        try:
            resp = self.session.get(f"{self.BASE_URL}/user/resume/", allow_redirects=False)
            # Если редирект на логин - не авторизован
            if resp.status_code == 302 and "login" in resp.headers.get("Location", ""):
                return False
            return resp.status_code == 200
        except Exception as e:
            print(f"Ошибка проверки авторизации: {e}")
            return False

    def get_user_info(self) -> Optional[dict]:
        """Получение информации о пользователе"""
        try:
            resp = self.session.get(f"{self.BASE_URL}/user/")
            if resp.status_code == 200:
                return {"status": "ok", "url": resp.url}
            return None
        except Exception as e:
            print(f"Ошибка получения информации: {e}")
            return None

    def get_my_resumes(self) -> List[dict]:
        """Получение списка своих резюме"""
        params = {
            "page[limit]": 15,
            "page[offset]": 0,
            "filters[mine]": 1,
            "include": "resumeBirthDate,totalExperience,town,photo,detail,workType,publishedStatus,person",
        }
        try:
            resp = self.session.get(f"{self.API_URL}/resume/", params=params)
            if resp.status_code == 200:
                data = resp.json()
                resumes = []
                for item in data.get("data", []):
                    resumes.append({
                        "id": item.get("id"),
                        "type": item.get("type"),
                        "attributes": item.get("attributes", {}),
                    })
                return resumes
            return []
        except Exception as e:
            print(f"Ошибка получения резюме: {e}")
            return []

    def apply_to_vacancy(
        self,
        vacancy_id: str,
        resume_id: str,
        cover_letter: Optional[str] = "default",
        no_work_experience: bool = False
    ) -> dict:
        """
        Отклик на вакансию с сопроводительным письмом

        Args:
            vacancy_id: ID вакансии
            resume_id: ID резюме
            cover_letter: сопроводительное письмо (опционально)
            no_work_experience: нет опыта работы

        Returns:
            dict: результат отклика с chat_id
        """
        cv_app_id = str(uuid.uuid4())
        vacancy_response_id = str(uuid.uuid4())
        cv_app_type_id = str(uuid.uuid4())

        payload = {
            "data": {
                "id": cv_app_id,
                "type": "cvApplication",
                "attributes": {},
                "relationships": {
                    "vacancyResponse": {
                        "data": {
                            "id": vacancy_response_id,
                            "type": "vacancyResponse"
                        }
                    }
                }
            },
            "included": [
                {
                    "id": vacancy_response_id,
                    "type": "vacancyResponse",
                    "attributes": {"noWorkExperience": no_work_experience},
                    "relationships": {
                        "resume": {"data": {"id": resume_id, "type": "resume"}},
                        "vacancy": {"data": {"id": vacancy_id, "type": "vacancy"}},
                        "cvApplicationType": {"data": {"id": cv_app_type_id, "type": "cvApplicationType"}}
                    }
                },
                {"id": vacancy_id, "type": "vacancy", "attributes": {}},
                {"id": resume_id, "type": "resume", "attributes": {}},
                {
                    "id": cv_app_type_id,
                    "type": "cvApplicationType",
                    "attributes": {},
                    "relationships": {
                        "responseType": {"data": {"id": "default", "type": "cvApplicationTypeDictionary"}}
                    }
                },
                {"id": "default", "type": "cvApplicationTypeDictionary", "attributes": {}}
            ]
        }

        include_params = (
            "vacancyResponse,"
            "vacancyResponse.vacancy.resumeInteractions.status,"
            "vacancyResponse.vacancy.resumeInteractions.resume,"
            "vacancyResponse.vacancy.resumeInteractions.vacancyResponse,"
            "vacancyResponse.vacancy.detailInfo,"
            "vacancyResponse.vacancy.contactInfo,"
            "vacancyResponse.chat.resume,"
            "vacancyResponse.chat.company,"
            "vacancyResponse.resume,"
            "vacancyResponse.cvApplicationType.responseType,"
            "vacancyResponse.responseSource.sourceName"
        )

        try:
            resp = self.session.post(
                f"{self.API_URL}/cvApplication/",
                params={"include": include_params},
                json=payload
            )
            result = {
                "success": resp.status_code in (200, 201),
                "status_code": resp.status_code,
                "response": resp.json() if resp.text else {},
                "chat_id": None,
                "chat_url": None
            }

            # Извлекаем chat_id из ответа
            if result["success"] and result["response"]:
                chat_id = self._extract_chat_id(result["response"])
                result["chat_id"] = chat_id
                if chat_id:
                    result["chat_url"] = f"{self.BASE_URL}/chat/?chatId={chat_id}"

                # Отправляем сопроводительное письмо
                if chat_id and cover_letter:
                    letter = self.config.cover_letter if cover_letter == "default" else cover_letter
                    msg_result = self.send_message(chat_id, letter)
                    result["cover_letter_sent"] = msg_result.get("success", False)

            return result
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _extract_chat_id(self, response: dict) -> Optional[str]:
        """Извлечение chat_id из ответа API"""
        try:
            included = response.get("included", [])
            for item in included:
                if item.get("type") == "chat":
                    return item.get("id")
            # Альтернативный путь через relationships
            data = response.get("data", {})
            relationships = data.get("relationships", {})
            vacancy_response = relationships.get("vacancyResponse", {}).get("data", {})
            vr_id = vacancy_response.get("id")
            if vr_id:
                for item in included:
                    if item.get("type") == "vacancyResponse" and item.get("id") == vr_id:
                        chat_data = item.get("relationships", {}).get("chat", {}).get("data", {})
                        return chat_data.get("id")
        except Exception:
            pass
        return None

    def send_message(self, chat_id: str, message: str) -> dict:
        """
        Отправка сообщения в чат

        Args:
            chat_id: ID чата
            message: текст сообщения

        Returns:
            dict: результат отправки
        """
        message_id = str(uuid.uuid4())
        simple_message_id = str(uuid.uuid4())
        now = datetime.now().astimezone().isoformat()

        payload = {
            "data": {
                "id": message_id,
                "type": "chatMessage",
                "attributes": {
                    "createdOnClientAt": now
                },
                "relationships": {
                    "chat": {"data": {"id": chat_id, "type": "chat"}},
                    "simpleMessage": {"data": {"id": simple_message_id, "type": "simpleChatMessage"}}
                }
            },
            "included": [
                {"id": chat_id, "type": "chat", "attributes": {}},
                {"id": simple_message_id, "type": "simpleChatMessage", "attributes": {"message": message}}
            ]
        }

        include_params = (
            "chat,hr,messageType,simpleMessage,"
            "inviteMessage.vacancy.mainInfo,"
            "inviteMessage.vacancy.companyInfo,"
            "vacancyResponseMessage.vacancy.mainInfo,"
            "vacancyResponseMessage.vacancy.companyInfo"
        )

        try:
            resp = self.session.post(
                f"{self.API_URL}/chatMessage/",
                params={"include": include_params},
                json=payload
            )
            return {
                "success": resp.status_code in (200, 201),
                "status_code": resp.status_code,
                "response": resp.json() if resp.text else {}
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_chats(self, limit: int = 25) -> List[dict]:
        """Получение списка чатов"""
        params = {
            "page[limit]": limit,
            "page[offset]": 0,
            "include": "company,vacancy.mainInfo,lastMessage",
        }
        try:
            resp = self.session.get(f"{self.API_URL}/chat/", params=params)
            if resp.status_code == 200:
                data = resp.json()
                chats = []
                for item in data.get("data", []):
                    chats.append({
                        "id": item.get("id"),
                        "attributes": item.get("attributes", {}),
                    })
                return chats
            return []
        except Exception as e:
            print(f"Ошибка получения чатов: {e}")
            return []

    def search_vacancies(
        self,
        keywords: str = "",
        limit: int = 20,
        offset: int = 0
    ) -> dict:
        """
        Поиск вакансий

        Args:
            keywords: ключевые слова
            limit: количество результатов
            offset: смещение

        Returns:
            dict: {total: int, vacancies: list}
        """
        params = {
            "page[limit]": limit,
            "page[offset]": offset,
            "filters[keywords]": keywords,
            "include": "mainInfo,companyInfo",
        }
        try:
            resp = self.session.get(f"{self.API_URL}/vacancy/", params=params)
            if resp.status_code == 200:
                data = resp.json()
                total = data.get("meta", {}).get("total", 0)

                # Собираем included в словарь
                included_map = {}
                for item in data.get("included", []):
                    key = f'{item["type"]}_{item["id"]}'
                    included_map[key] = item

                vacancies = []
                for item in data.get("data", []):
                    vid = item.get("id")
                    rels = item.get("relationships", {})

                    # mainInfo
                    main_id = rels.get("mainInfo", {}).get("data", {}).get("id")
                    main = included_map.get(f"vacancyMainInfo_{main_id}", {}).get("attributes", {})

                    # companyInfo
                    company_id = rels.get("companyInfo", {}).get("data", {}).get("id")
                    company = included_map.get(f"vacancyCompanyInfo_{company_id}", {}).get("attributes", {})

                    vacancies.append({
                        "id": vid,
                        "title": main.get("profession", ""),
                        "company": company.get("name", ""),
                        "salary_min": main.get("minSalary", 0),
                        "salary_max": main.get("maxSalary", 0),
                        "url": f"{self.BASE_URL}/vakansii/{vid}.html",
                    })
                return {"total": total, "vacancies": vacancies}
            return {"total": 0, "vacancies": []}
        except Exception as e:
            print(f"Ошибка поиска вакансий: {e}")
            return {"total": 0, "vacancies": []}

    def auto_apply(
        self,
        keywords: List[str] = None,
        limit: int = None,
        max_pages: int = None,
        resume_id: str = None
    ) -> dict:
        """
        Автоматический поиск и отклик на вакансии

        Args:
            keywords: список ключевых слов (по умолчанию из .env)
            limit: лимит вакансий на страницу (по умолчанию из .env)
            max_pages: максимум страниц на ключевое слово (по умолчанию из .env)
            resume_id: ID резюме (по умолчанию из .env)

        Returns:
            dict: статистика откликов
        """
        keywords = keywords or self.config.search_keywords
        limit = limit or self.config.search_limit
        max_pages = max_pages or self.config.max_pages
        resume_id = resume_id or self.config.resume_id

        if not keywords:
            return {"error": "Не указаны ключевые слова для поиска"}
        if not resume_id:
            return {"error": "Не указан resume_id"}

        stats = {
            "total_found": 0,
            "applied": 0,
            "failed": 0,
            "skipped": 0,
            "results": []
        }

        applied_ids = set()  # Чтобы не откликаться дважды

        for kw in keywords:
            print(f"\n🔍 Поиск: {kw}")

            # Загружаем несколько страниц
            all_vacancies = []
            for page in range(max_pages):
                offset = page * limit
                search_result = self.search_vacancies(kw, limit=limit, offset=offset)
                vacancies = search_result["vacancies"]

                if not vacancies:
                    break  # Больше нет результатов

                all_vacancies.extend(vacancies)
                total = search_result.get("total", 0)

                if page == 0:
                    print(f"   Найдено: {total} вакансий, загружаем до {min(total, limit * max_pages)}")

                if offset + limit >= total:
                    break  # Достигли конца

            stats["total_found"] += len(all_vacancies)

            for v in all_vacancies:
                vid = v["id"]

                if vid in applied_ids:
                    stats["skipped"] += 1
                    continue
                applied_ids.add(vid)

                result = self.apply_to_vacancy(vacancy_id=vid, resume_id=resume_id)

                entry = {
                    "vacancy_id": vid,
                    "title": v["title"],
                    "company": v["company"],
                    "success": result["success"],
                    "chat_url": result.get("chat_url"),
                    "cover_letter_sent": result.get("cover_letter_sent"),
                }

                if result["success"]:
                    stats["applied"] += 1
                    status = "✅"
                    if result.get("cover_letter_sent"):
                        status += " 💬"
                else:
                    stats["failed"] += 1
                    status = "❌"
                    entry["error"] = result.get("error", str(result.get("status_code")))

                print(f"  {status} {v['title']} @ {v['company']}")
                stats["results"].append(entry)

        print(f"\n📊 Итого: отправлено {stats['applied']}, ошибок {stats['failed']}, пропущено {stats['skipped']}")
        return stats


# Для обратной совместимости
SuperjobAuth = SuperjobAPI


# Запуск авто-откликов
if __name__ == "__main__":
    api = SuperjobAPI()

    print("=== SuperJob Auto-Apply ===")
    print(f"Browser: {api.config.browser}")
    print(f"Resume ID: {api.config.resume_id}")
    print(f"Keywords: {', '.join(api.config.search_keywords)}")
    print(f"Limit: {api.config.search_limit} вакансий/страница x {api.config.max_pages} страниц = до {api.config.search_limit * api.config.max_pages} на keyword")
    print()

    # Авторизация из кеша или браузера
    if api.auth_from_browser(api.config.browser):
        print("✅ Авторизация успешна!\n")

        # Запуск авто-откликов
        stats = api.auto_apply()

        # Сохраняем результаты в файл
        import json
        results_file = os.path.join(os.path.dirname(__file__), "results.json")
        with open(results_file, "w", encoding="utf-8") as f:
            json.dump(stats, f, ensure_ascii=False, indent=2)
        print(f"\n💾 Результаты сохранены в {results_file}")
    else:
        print("❌ Ошибка авторизации")