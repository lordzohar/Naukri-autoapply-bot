"""
Naukri Auto-Apply Bot - Recommended Jobs Edition
=================================================
Applies to recommended jobs on Naukri.com's dedicated page.
Selects up to 5 jobs, clicks Apply, then handles the chatbot
questionnaire drawer with a self-learning answer system.

Key features:
  - Radio buttons: auto-filled from CSV, or clicked by user in browser
  - Free-text questions: detected via contenteditable div, user types in browser
  - Self-learning: watches what you answer in the browser, saves to CSV automatically
  - Next run: previously seen questions are auto-filled

Usage:
    1. Copy .env.example to .env and fill in your details
    2. pip install -r requirements.txt
    3. python Naukri-Recommended.py

Page: https://www.naukri.com/mnjuser/recommendedjobs
"""

import os
import time
import csv
import difflib
import logging
import re
from datetime import datetime
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.edge.service import Service as EdgeService
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, ElementClickInterceptedException, StaleElementReferenceException

try:
    from webdriver_manager.microsoft import EdgeChromiumDriverManager
    WEBDRIVER_MANAGER_AVAILABLE = True
except ImportError:
    WEBDRIVER_MANAGER_AVAILABLE = False

# ------------------------------------------------------------
# Configuration
# ------------------------------------------------------------
load_dotenv()

NAUKRI_EMAIL = os.getenv('NAUKRI_EMAIL', '')
NAUKRI_PASSWORD = os.getenv('NAUKRI_PASSWORD', '')
MAX_SELECT = 5
ANSWERS_CSV = "application_answers.csv"

# ------------------------------------------------------------
# Logging Setup
# ------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


# ============================================================
# Answer Knowledge Base (CSV) — fixed header handling
# ============================================================

def load_answers():
    """
    Load question→answer mappings from CSV.
    Returns a dict: {question_text: answer}
    Handles the case where header row might be corrupted.
    """
    answers = {}
    if not os.path.exists(ANSWERS_CSV):
        logger.info(f"No existing {ANSWERS_CSV}, starting fresh.")
        return answers

    try:
        with open(ANSWERS_CSV, 'r', encoding='utf-8') as f:
            content = f.read().strip()
            if not content:
                return answers

            lines = content.split('\n')
            # Find the actual header line
            header_idx = -1
            for i, line in enumerate(lines):
                if line.startswith('question_text,'):
                    header_idx = i
                    break

            if header_idx == -1:
                logger.warning("No header found in CSV, recreating.")
                return answers

            # Re-read properly with DictReader
            reader = csv.DictReader(lines)
            for row in reader:
                q = (row.get('question_text') or '').strip()
                a = (row.get('answer') or '').strip()
                if q and a:
                    answers[q] = a

        logger.info(f"Loaded {len(answers)} known answers from {ANSWERS_CSV}")
    except Exception as e:
        logger.warning(f"Could not load {ANSWERS_CSV}: {e}")

    return answers


def fuzzy_lookup(question_text, known_answers, threshold=0.72):
    """Return the stored answer for question_text, using fuzzy matching as fallback."""
    if question_text in known_answers:
        return known_answers[question_text]
    matches = difflib.get_close_matches(
        question_text, known_answers.keys(), n=1, cutoff=threshold
    )
    if matches:
        logger.info(f"   ~ Fuzzy match: '{matches[0]}' → using stored answer")
        return known_answers[matches[0]]
    return None


def save_answer(question_text, answer, field_type="text"):
    """
    Append a new question→answer pair to the CSV.
    Creates header if file doesn't exist or is empty.
    """
    needs_header = False
    if not os.path.exists(ANSWERS_CSV):
        needs_header = True
    else:
        with open(ANSWERS_CSV, 'r', encoding='utf-8') as f:
            content = f.read().strip()
            if not content:
                needs_header = True

    try:
        mode = 'a' if os.path.exists(ANSWERS_CSV) else 'w'
        with open(ANSWERS_CSV, 'a', encoding='utf-8', newline='') as f:
            writer = csv.writer(f)
            if needs_header:
                writer.writerow(['question_text', 'answer', 'field_type', 'created_at'])
            writer.writerow([question_text, answer, field_type, datetime.now().isoformat()])
        logger.info(f"💾 Saved: '{question_text}' → '{answer}'")
    except Exception as e:
        logger.error(f"Could not save to {ANSWERS_CSV}: {e}")


# ============================================================
# Browser Setup
# ============================================================

def create_edge_driver():
    """Create and return an Edge WebDriver instance."""
    options = webdriver.EdgeOptions()
    options.add_argument("--start-maximized")
    options.add_argument("--disable-notifications")

    if WEBDRIVER_MANAGER_AVAILABLE:
        logger.info("Using webdriver-manager to auto-download EdgeDriver...")
        service = EdgeService(EdgeChromiumDriverManager().install())
    else:
        service = EdgeService()

    driver = webdriver.Edge(service=service, options=options)
    return driver


def login_naukri(driver):
    """Log in to Naukri.com."""
    logger.info("Logging in to Naukri.com...")
    driver.get('https://login.naukri.com/')
    time.sleep(3)

    WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.ID, 'usernameField'))
    )

    driver.find_element(By.ID, 'usernameField').send_keys(NAUKRI_EMAIL)
    passwd = driver.find_element(By.ID, 'passwordField')
    passwd.send_keys(NAUKRI_PASSWORD)
    passwd.send_keys(Keys.ENTER)

    time.sleep(8)
    logger.info("Login completed.")


# ============================================================
# Step 1: Select jobs & click Apply
# ============================================================

def select_jobs_and_apply(driver):
    """
    Select up to 5 jobs by clicking their checkboxes, then click Apply.
    Assumes we're already on the recommended jobs page.
    """
    logger.info("=" * 50)
    logger.info("STEP 1: Selecting jobs...")
    logger.info("=" * 50)

    try:
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "article.jobTuple"))
        )
    except TimeoutException:
        logger.error("No job cards found.")
        return False

    job_cards = driver.find_elements(By.CSS_SELECTOR, "article.jobTuple")
    logger.info(f"Found {len(job_cards)} job cards.")

    if not job_cards:
        logger.warning("No recommended jobs available.")
        return False

    selected = 0
    for card in job_cards:
        if selected >= MAX_SELECT:
            break
        try:
            if not card.find_elements(By.CSS_SELECTOR, ".tuple-check-box i"):
                continue

            checked_icon = card.find_elements(By.CSS_SELECTOR,
                ".tuple-check-box i.naukicon-ot-Checked, .tuple-check-box i.naukicon-ot-checkbox-selected")
            if checked_icon:
                continue

            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", card)
            time.sleep(0.5)

            cb = card.find_element(By.CSS_SELECTOR, ".tuple-check-box i.naukicon, .tuple-check-box")
            driver.execute_script("arguments[0].click();", cb)
            selected += 1

            try:
                title = card.find_element(By.CSS_SELECTOR, ".title.typ-16Bold").text
            except NoSuchElementException:
                title = "Unknown"
            logger.info(f"  [{selected}/{MAX_SELECT}] ✓ {title}")
            time.sleep(1)
        except Exception as e:
            logger.warning(f"  Select error: {e}")

    if selected == 0:
        logger.warning("No jobs were selected.")
        return False

    try:
        time.sleep(2)
        apply_btn = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "button.multi-apply-button"))
        )
        if apply_btn.get_attribute('disabled') is not None:
            logger.warning("Apply button disabled after selection.")
            return False

        driver.execute_script("arguments[0].click();", apply_btn)
        logger.info(f"✓ Clicked Apply for {selected} jobs!")
        time.sleep(3)
        return True

    except (TimeoutException, ElementClickInterceptedException) as e:
        logger.error(f"Could not click Apply: {e}")
        return False


# ============================================================
# Step 2: Handle the Chatbot Drawer Questions
# ============================================================

def handle_chatbot_drawer(driver, known_answers):
    """
    After clicking Apply, the chatbot drawer appears.

    Detection order every iteration:
    1. Radio buttons visible → auto-fill or log "unknown" + wait for browser click
    2. Contenteditable text div visible → auto-fill or wait for user to type in browser
    3. Save button ready → click it
    4. Drawer closed → done
    """
    logger.info("=" * 50)
    logger.info("STEP 2: Chatbot questionnaire...")
    logger.info("=" * 50)

    # Wait for the chatbot drawer
    try:
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "[id*='ChatbotContainer'], .chatbot_Drawer"))
        )
        logger.info("Chatbot drawer appeared.")
        time.sleep(3)
    except TimeoutException:
        logger.info("No chatbot drawer. Application may be complete.")
        return True

    # Track the last known bot message count so we can detect new questions
    last_bot_msg_count = 0

    for iteration in range(60):  # 60 * 2s = up to 2 min waiting
        time.sleep(2)

        try:
            # If drawer closed, we're done
            if not is_drawer_open(driver):
                logger.info("Drawer closed. ✓")
                return True

            # --- 1. Radio buttons ---
            if handle_radio_buttons(driver, known_answers):
                continue

            # --- 2. Contenteditable text field (chatbot free-text input) ---
            if handle_contenteditable(driver, known_answers):
                continue

            # --- 3. Save button ready? ---
            try:
                save_btn = find_save_button(driver)
                if save_btn and click_save_button(driver, save_btn):
                    logger.info("Save button ready. Clicking...")
                    time.sleep(3)
                    continue
            except Exception:
                pass

            # --- 4. If none of the above, log and wait for user to interact ---
            bot_msgs = driver.find_elements(By.CSS_SELECTOR, ".chatbot_ListItem.botItem .msg, .chatbot_ListItem .botMsg .msg")
            if len(bot_msgs) > last_bot_msg_count:
                for msg in bot_msgs[last_bot_msg_count:]:
                    text = msg.text.strip()
                    if text:
                        logger.info(f"🤖 Bot asks: '{text}'")
                last_bot_msg_count = len(bot_msgs)

            user_msg_count = len(driver.find_elements(By.CSS_SELECTOR, ".chatbot_ListItem.userItem .msg, .userMsg .msg"))
            if user_msg_count > 0:
                logger.info(f"  Detected {user_msg_count} user answers. Waiting for next question...")

        except StaleElementReferenceException:
            # DOM re-rendered — retry on next iteration
            continue
        except Exception as e:
            # Catch any unexpected errors to prevent crash
            logger.warning(f"  Iteration error (retrying): {e}")
            continue

    logger.warning("Timed out waiting for drawer to complete.")
    return False


def is_drawer_open(driver):
    """Check if the chatbot drawer is still visible with active content."""
    try:
        containers = driver.find_elements(By.CSS_SELECTOR, "[id*='ChatbotContainer']")
        for c in containers:
            if c.is_displayed():
                return True
        return False
    except Exception:
        return False


def get_latest_bot_question(driver):
    """Get the text of the most recent bot question message."""
    try:
        msgs = driver.find_elements(By.CSS_SELECTOR,
            ".chatbot_ListItem.botItem .msg, .chatbot_ListItem .botMsg .msg")
        if msgs:
            return msgs[-1].text.strip()
    except Exception:
        pass
    return None


def get_latest_user_answer(driver):
    """
    Get the text of the most recent user answer submitted (for learning).
    Returns None if no user message found.
    """
    try:
        msgs = driver.find_elements(By.CSS_SELECTOR,
            ".chatbot_ListItem.userItem .msg, .userMsg .msg")
        if msgs:
            return msgs[-1].text.strip()
    except Exception:
        pass
    return None


def get_user_message_count(driver):
    """Count how many user messages are in the chat."""
    try:
        return len(driver.find_elements(By.CSS_SELECTOR,
            ".chatbot_ListItem.userItem .msg, .userMsg .msg"))
    except Exception:
        return 0


# ============================================================
# Handler: Radio Buttons
def _click_save_after_radio(driver):
    """Click the save button right after selecting a radio option."""
    try:
        save_btn = find_save_button(driver)
        if save_btn and click_save_button(driver, save_btn):
            logger.info("   Clicked Save after radio selection.")
            time.sleep(2)
    except Exception:
        pass


# ============================================================

def handle_radio_buttons(driver, known_answers):
    """
    Check for radio button question. If found:
      - Known answer → auto-click
      - Unknown answer → log it, wait for user to click in browser, then save
    """
    # Check if radio container exists and is visible (using fresh reference each time)
    try:
        container = driver.find_element(By.CSS_SELECTOR, ".singleselect-radiobutton-container")
        if not container.is_displayed():
            return False
    except NoSuchElementException:
        return False

    question_text = get_latest_bot_question(driver) or "RadioQuestion"

    # Freshly fetch radios and labels each time they're needed (DOM may re-render)
    radio_buttons = container.find_elements(By.CSS_SELECTOR, ".ssrc__radio")
    labels = container.find_elements(By.CSS_SELECTOR, ".ssrc__label")

    options = [rb.get_attribute('value') or lbl.text.strip()
               for rb, lbl in zip(radio_buttons, labels)]

    logger.info(f"📋 Radio: '{question_text}'")
    logger.debug(f"   Options: {options}")

    # KNOWN ANSWER → auto-fill (use fresh references)
    known = fuzzy_lookup(question_text, known_answers)
    if known:
        radios = container.find_elements(By.CSS_SELECTOR, ".ssrc__radio")
        lbls = container.find_elements(By.CSS_SELECTOR, ".ssrc__label")
        for rb in radios:
            try:
                if rb.get_attribute('value') == known or rb.get_attribute('id') == known:
                    driver.execute_script("arguments[0].click();", rb)
                    logger.info(f"   ✓ Auto-filled: '{known}'")
                    time.sleep(1)
                    _click_save_after_radio(driver)
                    return True
            except Exception:
                continue
        for lbl in lbls:
            try:
                if lbl.text.strip().lower() == known.lower():
                    driver.execute_script("arguments[0].click();", lbl)
                    logger.info(f"   ✓ Auto-filled: '{known}'")
                    time.sleep(1)
                    _click_save_after_radio(driver)
                    return True
            except Exception:
                continue
        # If known answer didn't match any option, fall through to unknown flow

    # UNKNOWN → log and wait for user to click in browser
    logger.info(f"   ❓ Unknown radio. Options: {options}")
    logger.info("   👆 Click your answer in the browser...")

    # Wait for user to click one — re-fetch elements every iteration to avoid stale references
    waited = 0
    while waited < 30:  # up to 60 seconds
        time.sleep(2)
        waited += 2

        # Check if container still exists
        try:
            current_container = driver.find_element(By.CSS_SELECTOR, ".singleselect-radiobutton-container")
        except NoSuchElementException:
            return False

        # Re-fetch radios & labels fresh every poll cycle to avoid stale references
        try:
            radios = current_container.find_elements(By.CSS_SELECTOR, ".ssrc__radio")
            lbls = current_container.find_elements(By.CSS_SELECTOR, ".ssrc__label")
        except Exception:
            radios, lbls = [], []

        if not radios:
            if waited % 10 == 0:
                logger.info(f"   Waiting for radio options to load... ({waited}s)")
            continue

        for rb, lbl in zip(radios, lbls):
            try:
                if rb.is_selected():
                    chosen = lbl.text.strip()
                    logger.info(f"   ✓ User selected: '{chosen}'")
                    save_answer(question_text, chosen, "radio")
                    time.sleep(1)
                    return True
            except StaleElementReferenceException:
                # Element went stale — will retry on next iteration
                continue
            except Exception:
                continue

        # Check if container is no longer displayed (next question loaded)
        try:
            if not current_container.is_displayed():
                # The radio question was answered (by user) and replaced with next question
                return True
        except Exception:
            return True

        if waited % 10 == 0:
            logger.info(f"   Still waiting for you to click an option... ({waited}s)")

    logger.warning("   Timed out waiting for radio selection.")
    return False


# ============================================================
# Handler: Contenteditable (Chatbot Free-Text Input)
# ============================================================

def handle_contenteditable(driver, known_answers):
    """
    Check for the chatbot's free-text input (div[contenteditable="true"]).
    Known answer → auto-type and click save.
    Unknown → log, wait for user to type & submit in browser, extract & save.
    """
    text_area = find_chat_text_area(driver)
    if not text_area:
        return False

    question_text = get_latest_bot_question(driver) or "ChatbotTextQuestion"
    logger.info(f"📝 Text question: '{question_text}'")

    # KNOWN ANSWER → auto-fill
    known = fuzzy_lookup(question_text, known_answers)
    if known:
        try:
            fresh_text_area = find_chat_text_area(driver)
            if fresh_text_area:
                driver.execute_script("""
                    arguments[0].focus();
                    arguments[0].innerText = arguments[1];
                    arguments[0].dispatchEvent(new Event('input', {bubbles: true}));
                    arguments[0].dispatchEvent(new Event('change', {bubbles: true}));
                """, fresh_text_area, known)
                logger.info(f"   ✓ Auto-filled: '{known}'")
                time.sleep(0.5)
                try:
                    fresh_text_area.send_keys(Keys.RETURN)
                except Exception:
                    pass
                time.sleep(0.5)
        except Exception as e:
            logger.warning(f"   Could not auto-fill text: {e}")

        # Try clicking Save (with fresh reference)
        try:
            save_btn = find_save_button(driver)
            if save_btn and click_save_button(driver, save_btn):
                logger.info("   Clicked Save after auto-fill.")
                time.sleep(3)
                return True
        except Exception:
            pass
        return True

    # UNKNOWN → log and wait for user to type & submit in browser
    current_user_msg_count = get_user_message_count(driver)
    logger.info(f"   ❓ Unknown text question.")
    logger.info("   ✏️ Type your answer in the browser and click Send/Save...")

    waited = 0
    while waited < 60:
        time.sleep(2)
        waited += 2

        try:
            # Did user submit an answer? (user message count increased)
            new_count = get_user_message_count(driver)
            if new_count > current_user_msg_count:
                answer = get_latest_user_answer(driver)
                if answer:
                    logger.info(f"   ✓ User answered: '{answer}'")
                    save_answer(question_text, answer, "text")
                    time.sleep(2)
                    return True

            if not is_drawer_open(driver):
                return True
        except StaleElementReferenceException:
            # DOM re-rendered — retry next iteration
            continue
        except Exception:
            continue

        if waited % 10 == 0:
            logger.info(f"   Still waiting for you to type & send... ({waited}s)")

    logger.warning("   Timed out waiting for text answer.")
    return False


def click_save_button(driver, save_btn):
    """Click the save/send button, tolerating a missing 'send' ancestor."""
    try:
        parent = save_btn.find_element(By.XPATH, "./ancestor::*[contains(@class,'send')]")
        if 'disabled' in (parent.get_attribute('class') or ''):
            return False  # genuinely disabled
    except Exception:
        pass  # no such ancestor — try clicking anyway
    driver.execute_script("arguments[0].click();", save_btn)
    return True


def find_chat_text_area(driver):
    """
    Find the chatbot's free-text input area inside the drawer.
    It's a div with contenteditable="true", not a standard input.
    """
    try:
        # Strategy 1: The chatbot input container inside the drawer
        elements = driver.find_elements(By.CSS_SELECTOR,
            ".chatbot_SendMessageContainer .textArea[contenteditable='true'], "
            ".chatbot_InputContainer .textArea[contenteditable='true'], "
            "#userInput__g651km1xsInputBox, "
            "div.textArea[contenteditable='true']"
        )
        for el in elements:
            if el.is_displayed() and el.is_enabled():
                return el
    except Exception:
        pass
    return None


def find_save_button(driver):
    """
    Find the Save/Send button in the chatbot footer.
    Uses generic selectors since the IDs are dynamic.
    """
    try:
        selectors = [
            ".sendMsg",
            ".sendMsgbtn_container .sendMsg",
            "[class*='sendMsg']",
            "div.sendMsg",
        ]
        for sel in selectors:
            els = driver.find_elements(By.CSS_SELECTOR, sel)
            for el in els:
                if el.is_displayed():
                    return el
    except Exception:
        pass
    return None


# ============================================================
# Main
# ============================================================

def main():
    """Main entry point — loops until no recommended jobs remain."""
    logger.info("=" * 50)
    logger.info("Naukri Recommended Jobs Bot")
    logger.info("=" * 50)

    if not NAUKRI_EMAIL or not NAUKRI_PASSWORD:
        logger.error("Set NAUKRI_EMAIL and NAUKRI_PASSWORD in .env")
        return

    known_answers = load_answers()
    total_applied = 0

    driver = None
    try:
        driver = create_edge_driver()
        login_naukri(driver)

        # Loop: keep applying until no more recommended jobs
        while True:
            # Navigate fresh each iteration
            driver.get('https://www.naukri.com/mnjuser/recommendedjobs')
            time.sleep(4)

            # Select up to 5 jobs and click Apply
            if not select_jobs_and_apply(driver):
                logger.info("No more jobs to apply to.")
                break

            # Handle chatbot questionnaire (auto-fills known answers, learns new ones)
            handle_chatbot_drawer(driver, known_answers)
            total_applied += MAX_SELECT
            known_answers = load_answers()  # pick up anything just learned

            logger.info(f"Total applied so far: ~{total_applied}")
            logger.info("Returning to recommended page for more jobs...")
            time.sleep(3)

        logger.info("=" * 50)
        logger.info(f"✅ Complete! Applied to ~{total_applied} jobs total.")
        logger.info("=" * 50)

    except Exception as e:
        logger.exception(f"Error: {e}")
    finally:
        if driver:
            try:
                time.sleep(2)
                driver.quit()
            except Exception:
                pass


if __name__ == "__main__":
    main()