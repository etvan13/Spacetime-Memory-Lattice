**Spacetime Memory Lattice**

**1. Download Your ChatGPT Data**
1) Go to OpenAI Account → Data Export
2) Request an export and wait for the email
3) Download and unzip the .zip file

**2. Place Raw HTML**
1) Move the unzipped contents into:
'''SortGPT/GPTData/'''
2) You should now have SortGPT/GPTData/chat.html and other relevant data

**3. Extract JSON**
'''cd SortGPT'''
'''python extractor.py'''
⚠️ This will take some time
This generates:
  * GPTData/conversations.json
  * GPTData/assets.json
These are used to match conversation titles and linked file attachments.

**4. Sort Conversations**
'''python GPTSort.py'''
This creates a GPTSorted/ folder with one folder per conversation, each containing:
  * A .json file with messages
  * Any attachments that were linked in the conversation

***5. Store into Coordinates***
Navigate back to the project root
'''cd ..'''
Run script to store GPT data into coordinate structure
'''python navigation_hub.py'''
  * Choose option 3 (recurse store)
  * For input, point to the GPTSorted/ directory
  * Set base data dir as data

This will assign each conversation to a path through the coordinate space, storing:
  * Messages in deterministic coordinates
  * Attachments in nested folders
  * A mapping in data/conversation_index.txt

6. Restore a Conversation
To bring back a saved conversation:
'''python navigation_hub.py'''
  * Choose option 2 (restore)
  * Look up the starting coordinate and key in:
  data/conversation_index.txt
  * Enter the coordinate (e.g., 00 00 00 00 00 00)
  and the key (conversation folder name)
This will replay the blocks, printing user/assistant messages and attachments.


