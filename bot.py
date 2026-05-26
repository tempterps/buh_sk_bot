import os
import sys
import threading
import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
import psycopg2
from psycopg2.extras import Json
from telebot import TeleBot, types
from dotenv import load_dotenv





load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
CONTACT_URL = "https://t.me/buh_sk"

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не знайдено у .env")

bot = TeleBot(BOT_TOKEN)


def get_db_connection():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL не найден в переменных окружения")
    return psycopg2.connect(DATABASE_URL)


def init_db():
    if not DATABASE_URL:
        print("DATABASE_URL не задан, логирование в БД отключено", flush=True)
        return

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS bot_events (
            id BIGSERIAL PRIMARY KEY,
            created_at TIMESTAMP NOT NULL DEFAULT NOW(),

            user_id BIGINT,
            username TEXT,
            first_name TEXT,
            language_code TEXT,

            chat_id BIGINT,

            event_type TEXT NOT NULL,
            message_text TEXT,
            callback_data TEXT,

            group_id TEXT,
            service_id TEXT,

            source TEXT,
            payload JSONB
        );
        """
    )
    conn.commit()
    cur.close()
    conn.close()


def log_event(
    user=None,
    chat_id=None,
    event_type="unknown",
    message_text=None,
    callback_data=None,
    group_id=None,
    service_id=None,
    source="telegram_bot",
    payload=None,
):
    if not DATABASE_URL:
        return

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO bot_events (
                user_id,
                username,
                first_name,
                language_code,
                chat_id,
                event_type,
                message_text,
                callback_data,
                group_id,
                service_id,
                source,
                payload
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                getattr(user, "id", None),
                getattr(user, "username", None),
                getattr(user, "first_name", None),
                getattr(user, "language_code", None),
                chat_id,
                event_type,
                message_text,
                callback_data,
                group_id,
                service_id,
                source,
                Json(payload or {}),
            ),
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as error:
        print(f"DB logging error: {error}", flush=True)

MAIN_MENU_TEXT = "📋 Дізнатись про послуги"
CONTACT_TEXT = "💬 Написати в Telegram"

SERVICE_GROUPS = {
    "consultation": {
        "title": "💬 Консультація",
        "description": "Швидко зрозуміти, що саме вам потрібно і який шлях буде найвигіднішим.",
        "items": ["consultation"],
    },
    "registration": {
        "title": "🏢 Реєстрація бізнесу",
        "description": "Запуск бізнесу в Словаччині без зайвої бюрократії та помилок у документах.",
        "items": ["zivnost_registration", "sro_registration"],
    },
    "vat": {
        "title": "🧾 ПДВ",
        "description": "Допомога з реєстрацією ПДВ (DPH) під ваш формат роботи та тип операцій.",
        "items": ["vat_7a", "vat_full"],
    },
    "declarations": {
        "title": "📑 Податкові декларації",
        "description": "Подача daňové priznanie вчасно, без штрафів і без плутанини.",
        "items": ["tax_zivnostnik", "tax_employee", "tax_fop"],
    },
    "legal": {
        "title": "📍 Юридична адреса та митниця (EORI)",
        "description": "Адреса для бізнесу, EORI та супровід суміжних адміністративних процесів.",
        "items": ["legal_address", "eori_registration"],
    },
    "bookkeeping": {
        "title": "📚 Бухгалтерський супровід",
        "description": "Постійний контроль бухгалтерії, звітності, ПДВ та комунікації з державними органами.",
        "items": ["bookkeeping_zivnost", "bookkeeping_company"],
    },
    "a1": {
        "title": "🛡 Отримання A1",
        "description": "Оформлення документів для легальної роботи та підтвердження страхування у міжнародних кейсах.",
        "items": ["a1_certificate"],
    },
}

SERVICES = {
    "consultation": {
        "group": "consultation",
        "title": "Отримати консультацію",
        "menu_title": "💬 Отримати консультацію",
        "pitch": (
            "Якщо ви прийшли з реклами, вам не потрібна загальна теорія. Вам потрібна чітка відповідь: "
            "яку послугу обрати, що робити далі і як не переплатити. Саме це ми даємо на консультації."
        ),
        "benefits": [
            "Пояснюємо словацькі правила простою українською мовою.",
            "Даємо не абстрактні поради, а план дій під вашу ситуацію.",
            "Підкажемо, що краще саме для вас: živnosť, s.r.o., DPH, 7a, бухгалтерський супровід чи разова послуга.",
        ],
        "what_we_do": [
            "Аналізуємо вашу ситуацію та запит.",
            "Пояснюємо ризики, строки, витрати й наступні кроки.",
            "Після дзвінка ви розумієте, яку послугу замовляти і що для цього підготувати.",
        ],
        "process": [
            "Ви залишаєте заявку або пишете в Telegram.",
            "Узгоджуємо дату та час дзвінка.",
            "Надсилаємо рахунок і посилання на Google Meet.",
            "Проводимо консультацію та відповідаємо на ваші питання по суті.",
        ],
        "documents": [
            "Короткий опис вашої ситуації.",
            "За наявності: виписка по бізнесу, попередні листи від податкової, договори або рахунки.",
        ],
        "timeline": "Зазвичай консультацію можна призначити найближчим часом після звернення.",
        "price": "45 € / година",
        "source_url": "https://buh.sk/buhgalterskie-kontultacii-slovakia/",
    },
    "zivnost_registration": {
        "group": "registration",
        "title": "Реєстрація живності (аналог ФОП)",
        "menu_title": "🧍 Реєстрація живності",
        "pitch": (
            "Živnosť часто є найшвидшим стартом у Словаччині. Ми беремо на себе бюрократію, "
            "щоб ви не витрачали дні на переклади правил, форми та походи по установах."
        ),
        "benefits": [
            "Підкажемо, чи справді živnosť вигідна у вашому випадку.",
            "Пояснимо внески, податки та наступні кроки після реєстрації.",
            "За потреби відразу підключимо адресу, декларації та бухгалтерський супровід.",
        ],
        "what_we_do": [
            "Готуємо пакет документів для відкриття živnosť.",
            "Допомагаємо визначити види діяльності.",
            "Супроводжуємо реєстрацію та пояснюємо, що робити після отримання статусу підприємця.",
        ],
        "process": [
            "Збираємо базові дані й перевіряємо ваш кейс.",
            "Готуємо документи та узгоджуємо види діяльності.",
            "Подаємо пакет на реєстрацію.",
            "Після реєстрації пояснюємо внески, декларацію та наступні обов'язки.",
        ],
        "documents": [
            "Закордонний паспорт або ID.",
            "Адреса проживання в Словаччині.",
            "Дані про плановані види діяльності.",
            "За потреби: документ на юридичну адресу.",
        ],
        "timeline": (
            "Орієнтовно кілька робочих днів після отримання всіх даних. Соціальні внески у перший рік зазвичай "
            "не сплачуються, медичні залежать від вашого статусу."
        ),
        "price": "Орієнтовно від 120 € за реєстрацію, або від 275 € з юридичною адресою на рік",
        "source_url": "https://buh.sk/buhgalterski-poslugy-slovakia/",
    },
    "sro_registration": {
        "group": "registration",
        "title": "Реєстрація фірми SRO (аналог ТОВ)",
        "menu_title": "🏢 Реєстрація фірми SRO",
        "pitch": (
            "Коли вам потрібен більш захищений і професійний формат бізнесу, s.r.o. має сенс. Ми реєструємо "
            "компанію під ключ і ведемо процес від анкети до готових документів."
        ),
        "benefits": [
            "Оформлення онлайн без черг і хаосу.",
            "Правильно підготовлені документи і комунікація з державними органами на нашому боці.",
            "Можемо одразу додати юрадресу, ПДВ та бухгалтерський супровід.",
        ],
        "what_we_do": [
            "Готуємо повний пакет установчих документів.",
            "Подаємо документи до торгового реєстру.",
            "Супроводжуємо комунікацію з органами влади до завершення реєстрації.",
        ],
        "process": [
            "Ви заповнюєте анкету: назва, діяльність, адреса, засновники.",
            "Оплачуєте послугу та адміністративні витрати.",
            "Підписуєте документи й надсилаєте їх нам.",
            "Ми подаємо заявку на реєстрацію компанії.",
            "Надсилаємо підтвердження після успішного запису в реєстрі.",
        ],
        "documents": [
            "Дані засновника або засновників.",
            "Обрана назва компанії.",
            "Перелік видів діяльності.",
            "Адреса компанії або замовлення юридичної адреси.",
            "Нотаріально засвідчений підпис на установчих документах.",
        ],
        "timeline": "Зазвичай до 14 днів за умови нормальної роботи державних органів.",
        "price": (
            "Базовий пакет: 170 € + держзбір 220 €. Пакет з юрадресою: 315 € + держзбір 220 €. "
            "ALL Inclusive з річним бухобслуговуванням: 1615 € + держзбір 220 €."
        ),
        "source_url": "https://buh.sk/registracia-sro-v-slovakii/",
    },
    "eori_registration": {
        "group": "legal",
        "title": "Реєстрація на митниці (EORI)",
        "menu_title": "🌍 Реєстрація на митниці (EORI)",
        "pitch": (
            "Без EORI імпорт і експорт швидко впираються в бюрократію. Ми допоможемо оформити номер правильно, "
            "щоб ви не затримували поставки та не втрачали час на митних деталях."
        ),
        "benefits": [
            "Пояснюємо, коли EORI потрібен саме вам.",
            "Готуємо подачу без плутанини в митних формах.",
            "За потреби одразу допомагаємо з ПДВ та бухгалтерією для імпортно-експортних операцій.",
        ],
        "what_we_do": [
            "Перевіряємо, чи потрібен EORI для вашої моделі роботи.",
            "Готуємо заяву та супровідні дані.",
            "Супроводжуємо подачу й пояснюємо, як використовувати номер далі.",
        ],
        "process": [
            "Отримуємо базові дані про бізнес і зовнішньоекономічні операції.",
            "Готуємо документи на реєстрацію.",
            "Подаємо заявку до митних органів.",
            "Після отримання номера пояснюємо подальші кроки для імпорту або експорту.",
        ],
        "documents": [
            "Реєстраційні дані підприємця або компанії.",
            "Податковий номер / IČO / DIČ.",
            "Контактні дані та короткий опис товарних операцій.",
        ],
        "timeline": "Орієнтовно від кількох робочих днів, залежно від повноти документів та черги органу.",
        "price": "Орієнтовно від 79 €",
        "source_url": "https://buh.sk/orenda-juridicnoi-adresy-slovakia/",
    },
    "vat_7a": {
        "group": "vat",
        "title": "Реєстрація ПДВ за параграфом 7а",
        "menu_title": "🧾 ПДВ за параграфом 7а",
        "pitch": (
            "Параграф 7а часто потрібен тим, хто працює з послугами всередині ЄС. Помилка на старті тут дорого коштує, "
            "тому краще відразу оформити все правильно."
        ),
        "benefits": [
            "Пояснимо, чи підходить вам саме режим 7а, а не повна реєстрація DPH.",
            "Убережемо від зайвих обов'язків або неправильної моделі оподаткування.",
            "Після реєстрації покажемо, що і коли потрібно подавати далі.",
        ],
        "what_we_do": [
            "Аналізуємо ваш тип операцій із контрагентами з ЄС.",
            "Готуємо пакет для реєстрації за §7a.",
            "Пояснюємо подальшу звітність і правила роботи з інвойсами.",
        ],
        "process": [
            "Коротко вивчаємо ваші послуги, країни контрагентів і схему платежів.",
            "Готуємо заяву та подаємо на реєстрацію.",
            "Після підтвердження пояснюємо, як коректно працювати далі.",
        ],
        "documents": [
            "Дані живності або компанії.",
            "Опис послуг та контрагентів з ЄС.",
            "Контактні та реєстраційні дані бізнесу.",
        ],
        "timeline": "Орієнтовно кілька робочих днів після подачі повного пакета.",
        "price": "Орієнтовно від 89 €",
        "source_url": "https://buh.sk/orenda-juridicnoi-adresy-slovakia/",
    },
    "vat_full": {
        "group": "vat",
        "title": "Стати платником ПДВ",
        "menu_title": "🏷 Стати платником ПДВ",
        "pitch": (
            "Реєстрація платником DPH має сенс лише тоді, коли вона правильно підібрана під ваш бізнес. Ми допомагаємо не просто "
            "подати заявку, а й одразу побудувати безпечну модель роботи з ПДВ."
        ),
        "benefits": [
            "Перевіримо, чи потрібна вам реєстрація обов'язково або добровільно.",
            "Пояснимо, як зміняться рахунки, звіти та бухгалтерія.",
            "За потреби одразу беремо компанію або живність на подальший супровід.",
        ],
        "what_we_do": [
            "Оцінюємо підстави для реєстрації DPH.",
            "Готуємо заяву та супровідні документи.",
            "Пояснюємо, як далі подавати звіти й уникати типових помилок.",
        ],
        "process": [
            "Аналізуємо обороти, тип клієнтів і господарські операції.",
            "Готуємо пакет документів.",
            "Подаємо на реєстрацію та супроводжуємо відповідь органу.",
            "Після реєстрації пояснюємо правила роботи з DPH і звітністю.",
        ],
        "documents": [
            "Реєстраційні дані бізнесу.",
            "Інформація про обороти, інвойси або плановані операції.",
            "За потреби: підтвердження договорів, рахунків або економічної діяльності.",
        ],
        "timeline": "Строк залежить від типу реєстрації та перевірки податковою, але підготовку ми робимо одразу після отримання даних.",
        "price": "Орієнтовно від 149 € за реєстрацію",
        "source_url": "https://buh.sk/orenda-juridicnoi-adresy-slovakia/",
    },
    "tax_zivnostnik": {
        "group": "declarations",
        "title": "Податкова декларація для живностніка",
        "menu_title": "🧍 Для живностніка",
        "pitch": (
            "Daňové priznanie для živnostník має бути подане вчасно і правильно. Ми рахуємо, перевіряємо та подаємо так, щоб у вас не було "
            "неприємних сюрпризів із податковою."
        ),
        "benefits": [
            "Пояснюємо, які витрати можна врахувати, а які ні.",
            "Підкажемо, чи варто подавати odklad.",
            "Враховуємо внески, паушальні витрати або реальні витрати залежно від вашої моделі.",
        ],
        "what_we_do": [
            "Збираємо дані про доходи, витрати та внески.",
            "Готуємо декларацію й розраховуємо суму податку.",
            "Подаємо декларацію або оформлюємо відтермінування за потреби.",
        ],
        "process": [
            "Ви надсилаєте документи та базову інформацію про діяльність.",
            "Ми перевіряємо комплектність і уточнюємо питання.",
            "Готуємо декларацію та погоджуємо результат.",
            "Подаємо до строку та пояснюємо, як оплатити податок.",
        ],
        "documents": [
            "Дані про дохід за рік.",
            "Виписки, фактури, чеки або облік витрат.",
            "Інформація про сплачені медичні та соціальні внески.",
            "За потреби: дані про іноземні доходи.",
        ],
        "timeline": "Стандартний строк подачі: до 31.03. Можна оформити odklad, якщо не встигаєте.",
        "price": "Орієнтовно від 120 €",
        "source_url": "https://buh.sk/%D0%BF%D0%BE%D0%B4%D0%B0%D0%BD%D0%BD%D1%8F-%D0%BF%D0%BE%D0%B4%D0%B0%D1%82%D0%BA%D0%BE%D0%B2%D0%BE%D1%97-%D0%B4%D0%B5%D0%BA%D0%BB%D0%B0%D1%80%D0%B0%D1%86%D1%96%D1%97-%D0%B2-%D1%81%D0%BB%D0%BE%D0%B2/",
    },
    "tax_employee": {
        "group": "declarations",
        "title": "Податкова декларація для найманого працівника",
        "menu_title": "👔 Для найманого працівника",
        "pitch": (
            "Навіть якщо у вас не бізнес, а робота за трудовим договором, податкова декларація або річний перерахунок можуть мати нюанси. "
            "Ми допоможемо закрити це питання без нервів і втрати часу."
        ),
        "benefits": [
            "Перевіряємо, чи справді вам потрібно подавати декларацію.",
            "Допомагаємо врахувати додаткові доходи, податкові бонуси та інші фактори.",
            "Пояснюємо все просто і без бухгалтерського жаргону.",
        ],
        "what_we_do": [
            "Аналізуємо ваші доходи та статус за рік.",
            "Готуємо декларацію або підказуємо оптимальний формат оформлення.",
            "Пояснюємо строки, оплату й подальші кроки.",
        ],
        "process": [
            "Ви надсилаєте довідки про доходи та короткий опис ситуації.",
            "Ми перевіряємо, чи потрібно подавати декларацію.",
            "Готуємо документи і допомагаємо з подачею.",
        ],
        "documents": [
            "Підтвердження доходів від роботодавця.",
            "Документи про додаткові доходи, якщо вони були.",
            "За потреби: документи на податкові бонуси або пільги.",
        ],
        "timeline": "Базовий строк подання також орієнтується на кінець березня, якщо декларація потрібна.",
        "price": "Орієнтовно від 60 €",
        "source_url": "https://buh.sk/%D0%BF%D0%BE%D0%B4%D0%B0%D0%BD%D0%BD%D1%8F-%D0%BF%D0%BE%D0%B4%D0%B0%D1%82%D0%BA%D0%BE%D0%B2%D0%BE%D1%97-%D0%B4%D0%B5%D0%BA%D0%BB%D0%B0%D1%80%D0%B0%D1%86%D1%96%D1%97-%D0%B2-%D1%81%D0%BB%D0%BE%D0%B2/",
    },
    "tax_fop": {
        "group": "declarations",
        "title": "Податкова декларація для ФОП",
        "menu_title": "📘 Для ФОП",
        "pitch": (
            "Якщо у вас нестандартний кейс: український ФОП, іноземні доходи, комбінований статус або кілька джерел доходу, тут потрібна "
            "не шаблонна подача, а уважна перевірка."
        ),
        "benefits": [
            "Розбираємо міжнародні та змішані кейси без плутанини.",
            "Допомагаємо зібрати логіку доходів і витрат у зрозумілу декларацію.",
            "Пояснюємо, які документи ще потрібно мати про запас.",
        ],
        "what_we_do": [
            "Аналізуємо джерела доходів і податковий статус.",
            "Підбираємо правильний підхід до заповнення декларації.",
            "Допомагаємо підготувати й подати документи без типових міжнародних помилок.",
        ],
        "process": [
            "Отримуємо опис вашого кейсу та документи.",
            "Проводимо короткий аналіз і повідомляємо, що ще потрібно.",
            "Готуємо декларацію та погоджуємо фінальний варіант.",
        ],
        "documents": [
            "Відомості про доходи в Україні та/або Словаччині.",
            "Банківські виписки, інвойси, акти або інші підтвердження доходу.",
            "Інформація про податковий статус та період перебування в Словаччині.",
        ],
        "timeline": "Строк залежить від складності кейсу, але краще звертатися завчасно до дедлайну подачі.",
        "price": "Орієнтовно від 95 €",
        "source_url": "https://buh.sk/buhgalterskie-kontultacii-slovakia/",
    },
    "legal_address": {
        "group": "legal",
        "title": "Оренда юридичної адреси",
        "menu_title": "📍 Оренда юр адреси",
        "pitch": (
            "Якщо не хочете прив'язувати бізнес до домашньої адреси або у вас немає власної нерухомості, юрадреса вирішує це питання "
            "швидко й легально."
        ),
        "benefits": [
            "Стабільна адреса в Братиславі для реєстрації бізнесу.",
            "Підходить для živnosť, s.r.o. і зміни вже існуючої адреси.",
            "Можемо одразу оформити весь пакет разом із реєстрацією бізнесу.",
        ],
        "what_we_do": [
            "Надаємо адресу для реєстрації бізнесу.",
            "Готуємо договір оренди адреси.",
            "За потреби вносимо зміни до державних реєстрів.",
        ],
        "process": [
            "Ви пишете, для чого саме потрібна адреса: živnosť, s.r.o. або зміна адреси.",
            "Ми уточнюємо деталі та перелік документів.",
            "Готуємо договір і, за потреби, супроводжуємо запис у реєстрах.",
        ],
        "documents": [
            "Дані підприємця або компанії.",
            "Інформація про те, чи це нова реєстрація, чи зміна адреси.",
            "За потреби: документи вже існуючого бізнесу.",
        ],
        "timeline": "Після заявки швидко узгоджуємо деталі; весь супровід реєстрації можна об'єднати в один процес.",
        "price": "155 € / рік",
        "source_url": "https://buh.sk/orenda-juridicnoi-adresy-slovakia/",
    },
    "bookkeeping_zivnost": {
        "group": "bookkeeping",
        "title": "Бухгалтерський супровід для живності",
        "menu_title": "🧍 Супровід для живності",
        "pitch": (
            "Живність здається простою лише на старті. Коли з'являються інвойси, витрати, внески, декларації й питання по ПДВ, важливо мати бухгалтера, "
            "який не губиться в деталях."
        ),
        "benefits": [
            "Пояснюємо цифри людською мовою, а не сухими термінами.",
            "Нагадуємо про строки й допомагаємо не зловити штрафи.",
            "Можемо вести від першої декларації до переходу на s.r.o., якщо бізнес виросте.",
        ],
        "what_we_do": [
            "Ведемо поточний облік доходів і витрат.",
            "Допомагаємо з внесками, деклараціями та питаннями по ПДВ.",
            "Консультуємо щодо оптимальної структури роботи і документів.",
        ],
        "process": [
            "Починаємо з короткої анкети та розуміння обсягу документів.",
            "Узгоджуємо формат роботи.",
            "Ви передаєте документи, ми ведемо облік і нагадуємо про важливі строки.",
        ],
        "documents": [
            "Банківські виписки.",
            "Фактури, чеки, договори.",
            "Дані про внески, якщо вони вже нараховуються.",
        ],
        "timeline": "Підключення можливе одразу після узгодження обсягу документів і формату співпраці.",
        "price": "Орієнтовно від 69 € / міс",
        "source_url": "https://buh.sk/buhgalterski-poslugy-slovakia/",
    },
    "bookkeeping_company": {
        "group": "bookkeeping",
        "title": "Бухгалтерський супровід для фірми",
        "menu_title": "🏢 Супровід для фірми",
        "pitch": (
            "Компанії потрібен не просто бухгалтер, а команда, яка подає звіти вчасно, тримає порядок у документах і швидко відповідає, коли виникає питання. "
            "Саме так працює buh.sk."
        ),
        "benefits": [
            "Повне ведення бухгалтерії, звітів, зарплат і внесків.",
            "Окремі пакети для компаній без ПДВ і з ПДВ.",
            "Комунікація українською мовою плюс словацька експертиза на боці команди.",
        ],
        "what_we_do": [
            "Ведемо повну бухгалтерію компанії.",
            "Подаємо звіти до податкової та працюємо з DPH.",
            "Рахуємо зарплати, внески та допомагаємо в поточних питаннях бізнесу.",
        ],
        "process": [
            "Ви заповнюєте анкету.",
            "Підписуємо договір.",
            "Передаєте документи, а ми беремо бухгалтерію на себе.",
        ],
        "documents": [
            "Банківські виписки.",
            "Вхідні та вихідні фактури.",
            "Чеки, касові документи, договори.",
            "За наявності працівників: дані по зарплатах і трудових договорах.",
        ],
        "timeline": "Підключення починається одразу після підписання договору та отримання документів.",
        "price": (
            "Без ПДВ: 89 € / міс або 169 € / міс. З ПДВ: 99 € / міс або 189 € / міс. "
            "Великі обсяги документів - індивідуально. Річна декларація оплачується окремо по ціні місячного пакета."
        ),
        "source_url": "https://buh.sk/buhgalter-sro-no-vat-bratislava/",
    },
    "a1_certificate": {
        "group": "a1",
        "title": "Отримання A1",
        "menu_title": "🛡 Отримання A1",
        "pitch": (
            "Якщо ви працюєте або відряджаєтеся між країнами ЄС, документ A1 важливий для підтвердження соціального страхування. "
            "Ми допоможемо пройти цей процес без зайвих затримок і неясностей."
        ),
        "benefits": [
            "Пояснюємо, коли A1 справді потрібен.",
            "Допомагаємо з підготовкою пакета під вашу модель роботи.",
            "Перевіряємо, чи все узгоджується з вашим статусом підприємця або компанії.",
        ],
        "what_we_do": [
            "Аналізуємо ваш кейс щодо роботи в іншій країні ЄС.",
            "Готуємо документи на оформлення A1.",
            "Пояснюємо, які підтвердження й дані потрібно мати надалі.",
        ],
        "process": [
            "Отримуємо короткий опис роботи, країну і період.",
            "Перевіряємо підстави для подачі.",
            "Готуємо пакет і супроводжуємо подачу.",
        ],
        "documents": [
            "Реєстраційні дані підприємця або компанії.",
            "Інформація про країну, період і характер роботи.",
            "За потреби: договори, підтвердження діяльності, дані про страхування.",
        ],
        "timeline": "Орієнтовний строк залежить від типу кейсу та органу, але підготовку ми починаємо одразу після отримання даних.",
        "price": "Орієнтовно від 99 €",
        "source_url": "https://buh.sk/orenda-juridicnoi-adresy-slovakia/",
    },
}


def main_reply_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row(types.KeyboardButton(MAIN_MENU_TEXT))
    markup.row(types.KeyboardButton(CONTACT_TEXT))
    return markup


def build_groups_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=1)
    for group_id, group in SERVICE_GROUPS.items():
        markup.add(types.InlineKeyboardButton(group["title"], callback_data=f"group:{group_id}"))
    markup.add(types.InlineKeyboardButton("💬 Написати нам", callback_data="contact:telegram"))
    return markup


def build_group_keyboard(group_id):
    group = SERVICE_GROUPS[group_id]
    markup = types.InlineKeyboardMarkup(row_width=1)
    for service_id in group["items"]:
        markup.add(types.InlineKeyboardButton(SERVICES[service_id]["menu_title"], callback_data=f"service:{service_id}"))
    markup.row(
        types.InlineKeyboardButton("⬅️ До розділів", callback_data="menu:services"),
        types.InlineKeyboardButton("💬 Написати нам", callback_data="contact:telegram"),
    )
    return markup


def build_service_keyboard(service_id):
    group_id = SERVICES[service_id]["group"]
    markup = types.InlineKeyboardMarkup(row_width=1)
    source_url = SERVICES[service_id].get("source_url")
    markup.add(types.InlineKeyboardButton("💬 Замовити цю послугу", callback_data="contact:telegram"))
    if source_url:
        markup.add(types.InlineKeyboardButton("🌐 Детальніше на сайті", url=source_url))
    markup.row(
        types.InlineKeyboardButton("⬅️ Назад", callback_data=f"group:{group_id}"),
        types.InlineKeyboardButton("🏠 Всі послуги", callback_data="menu:services"),
    )
    return markup


def format_bullets(items):
    return "\n".join(f"• {item}" for item in items)


def format_steps(items):
    return "\n".join(f"{index}. {item}" for index, item in enumerate(items, start=1))


def services_overview_text():
    return (
        "📋 Послуги BUH.SK\n\n"
        "Зазвичай клієнт хоче швидко зрозуміти 4 речі:\n"
        "• чи надаємо ми потрібну послугу\n"
        "• як саме проходить процес\n"
        "• які документи потрібні\n"
        "• скільки це коштує\n\n"
        "Оберіть розділ нижче. Усередині кожної послуги ви побачите коротке пояснення, як ми працюємо, що потрібно від вас і який бюджет варто планувати."
    )


def group_text(group_id):
    group = SERVICE_GROUPS[group_id]
    return f"{group['title']}\n\n{group['description']}\n\nОберіть потрібну послугу нижче."


def service_text(service_id):
    service = SERVICES[service_id]
    sections = [
        f"{service['menu_title']}\n\n{service['pitch']}",
        "Чому клієнти замовляють це у нас:\n" + format_bullets(service["benefits"]),
        "Що ми робимо:\n" + format_bullets(service["what_we_do"]),
        "Як проходить процес:\n" + format_steps(service["process"]),
        "Що потрібно від вас:\n" + format_bullets(service["documents"]),
        f"Строки:\n{service['timeline']}",
        f"Вартість:\n{service['price']}",
        "Якщо хочете, можемо відразу написати, який саме варіант найкраще підійде під вашу ситуацію.",
    ]
    return "\n\n".join(sections)


def send_or_edit(chat_id, text, reply_markup, message_id=None):
    if message_id:
        bot.edit_message_text(text, chat_id, message_id, reply_markup=reply_markup, disable_web_page_preview=True)
        return
    bot.send_message(chat_id, text, reply_markup=reply_markup, disable_web_page_preview=True)


def send_start(chat_id):
    welcome_text = (
        "Привіт! Це BUH.SK 🇸🇰\n\n"
        "Ми допомагаємо українцям у Словаччині з реєстрацією бізнесу, ПДВ, податковими деклараціями, "
        "юридичною адресою, бухгалтерією та суміжними питаннями.\n\n"
        "Натисніть кнопку нижче, щоб одразу подивитися послуги, або напишіть нам напряму."
    )
    markup = main_reply_keyboard()
    bot.send_message(chat_id, welcome_text, reply_markup=markup, disable_web_page_preview=True)


def send_contact_url(chat_id):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("💬 Відкрити Telegram", url=CONTACT_URL))
    bot.send_message(
        chat_id,
        "Натисніть кнопку нижче, щоб написати нам напряму.",
        reply_markup=markup,
        disable_web_page_preview=True,
    )


@bot.message_handler(commands=["start", "services"])
def start_command(message):
    log_event(
        user=message.from_user,
        chat_id=message.chat.id,
        event_type="start_command",
        message_text=message.text,
        payload={"command": message.text},
    )
    send_start(message.chat.id)


@bot.message_handler(func=lambda message: message.text == MAIN_MENU_TEXT)
def handle_main_menu(message):
    log_event(
        user=message.from_user,
        chat_id=message.chat.id,
        event_type="main_menu_clicked",
        message_text=message.text,
    )
    bot.send_message(
        message.chat.id,
        services_overview_text(),
        reply_markup=build_groups_keyboard(),
        disable_web_page_preview=True,
    )


@bot.message_handler(func=lambda message: message.text == CONTACT_TEXT)
def handle_contact(message):
    log_event(
        user=message.from_user,
        chat_id=message.chat.id,
        event_type="contact_clicked",
        message_text=message.text,
    )
    send_contact_url(message.chat.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("menu:"))
def menu_callback(call):
    bot.answer_callback_query(call.id)
    if call.data == "menu:services":
        log_event(
            user=call.from_user,
            chat_id=call.message.chat.id,
            event_type="services_menu_opened",
            callback_data=call.data,
        )
        send_or_edit(
            call.message.chat.id,
            services_overview_text(),
            build_groups_keyboard(),
            message_id=call.message.message_id,
        )


@bot.callback_query_handler(func=lambda call: call.data.startswith("group:"))
def group_callback(call):
    bot.answer_callback_query(call.id)
    group_id = call.data.split(":", 1)[1]
    log_event(
        user=call.from_user,
        chat_id=call.message.chat.id,
        event_type="group_opened",
        callback_data=call.data,
        group_id=group_id,
    )
    send_or_edit(
        call.message.chat.id,
        group_text(group_id),
        build_group_keyboard(group_id),
        message_id=call.message.message_id,
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("service:"))
def service_callback(call):
    bot.answer_callback_query(call.id)
    service_id = call.data.split(":", 1)[1]
    log_event(
        user=call.from_user,
        chat_id=call.message.chat.id,
        event_type="service_opened",
        callback_data=call.data,
        service_id=service_id,
    )
    send_or_edit(
        call.message.chat.id,
        service_text(service_id),
        build_service_keyboard(service_id),
        message_id=call.message.message_id,
    )


@bot.callback_query_handler(func=lambda call: call.data == "contact:telegram")
def contact_callback(call):
    bot.answer_callback_query(call.id)
    log_event(
        user=call.from_user,
        chat_id=call.message.chat.id,
        event_type="contact_intent",
        callback_data=call.data,
    )
    send_contact_url(call.message.chat.id)


@bot.message_handler(func=lambda message: True)
def fallback_handler(message):
    log_event(
        user=message.from_user,
        chat_id=message.chat.id,
        event_type="free_text_message",
        message_text=message.text,
    )
    bot.send_message(
        message.chat.id,
        "Щоб швидко знайти потрібну послугу, натисніть кнопку '📋 Дізнатись про послуги' або напишіть нам напряму.",
        reply_markup=main_reply_keyboard(),
        disable_web_page_preview=True,
    )





def run_bot():
    now = datetime.datetime.now()
    time = now.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{time}]  Запуск Telegram бота...\n", flush=True)
    bot.infinity_polling()

# --- 3. ЗАПУСК ОБОИХПРОЦЕССОВ ОДНОВРЕМЕННО ---
if __name__ == "__main__":
    init_db()
    run_bot()
    

