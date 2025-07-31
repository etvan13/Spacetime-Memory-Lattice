import pathlib, json, time
from pathlib import Path
from selenium import webdriver

# point to the chat.html inside GPTData
THIS_DIR = Path(__file__).resolve().parent
BASE_DIR = THIS_DIR.parent

data_dir = BASE_DIR / "GPTData" 
html_path = data_dir / "chat.html"

driver = webdriver.Chrome()
driver.get(f"file://{html_path}")

time.sleep(2)

conversations = driver.execute_script("return jsonData;")
assets        = driver.execute_script("return assetsJson;")
driver.quit()

# save into GPTData
with open(data_dir / "conversations.json", "w", encoding="utf-8") as f:
    json.dump(conversations, f, indent=2)
with open(data_dir / "assets.json", "w", encoding="utf-8") as f:
    json.dump(assets, f, indent=2)

print("Extracted JSON successfully.")
