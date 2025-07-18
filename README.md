[BOLD] Spacetime Memory Lattice

[BOLD] 1. Download Your ChatGPT Data
1) Go to OpenAI Account → Data Export
2) Request export, wait for email, download zip

[BOLD] 2. Place Raw HTML
1) Unzip into SortGPT/GPTData
2) You should now have SortGPT/GPTData/chat.html and other relevant data

[BOLD] 3. Extract JSON
[CODE] cd SortGPT
[CODE] python extractor.py
This generates:
  - GPTData/conversations.json
  - GPTData/assets.json
 (these help get large sized variables from the html file)

[BOLD] 4. Sort Conversations
[CODE] python GPTSort.py
Output appears under project_root/GPTSorted/
This sorting just stores each conversation in a directory named after the convo with a json file holding the conversation and relevant attachments in the directory as well.

[BOLD] 5. Store into Coordinates
[CODE] python navigation_hub.py
Choose option 3, point at GPTSorted, base data dir “data”
This will store all the blocks (user: (says something) AI: (responds)) at differing coordinates

[BOLD] 6. Restore a Conversation
[CODE] python navigation_hub.py
Choose option 2, enter start coord and key
This will allow you to gather a conversation's blocks back just by giving the starting coordinate and the conversation name as the key.
