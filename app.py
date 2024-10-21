import os
from flask import Flask, render_template, redirect, url_for, request, flash, jsonify
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField
from wtforms.validators import DataRequired, Length, EqualTo
from datetime import datetime
import time
import ipdb
import re
import json
import traceback
import uuid 

def generate_unique_id():
    return str(uuid.uuid4())

from openai import AzureOpenAI

client = AzureOpenAI(
    api_key="02427719893b42868f349a4668288963",
    api_version='2023-12-01-preview',
    azure_endpoint="https://shuningz.openai.azure.com/"
)

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_secret_key'

login_manager = LoginManager(app)
login_manager.login_view = 'login'

USER_DATA_FILE = 'users.txt'
CHAT_DATA_DIR = 'chats'

if not os.path.exists(CHAT_DATA_DIR):
    os.makedirs(CHAT_DATA_DIR)

class User(UserMixin):
    def __init__(self, id, username, password):
        self.id = id
        self.username = username
        self.password = password

@login_manager.user_loader
def load_user(user_id):
    with open(USER_DATA_FILE, 'r') as f:
        users = f.readlines()
        for user in users:
            uid, username, password = user.strip().split(',')
            if uid == user_id:
                return User(uid, username, password)
    return None

class RegistrationForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(min=4, max=20)])
    password = PasswordField('Password', validators=[DataRequired()])
    confirm_password = PasswordField('Confirm Password', validators=[DataRequired(), EqualTo('password')])
    submit = SubmitField('Sign Up')

class LoginForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired()])
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('Login')

@app.route('/')
def home():
    return render_template('home.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    form = RegistrationForm()
    if form.validate_on_submit():
        with open(USER_DATA_FILE, 'a') as f:
            user_id = str(len(open(USER_DATA_FILE).readlines()) + 1)
            f.write(f"{user_id},{form.username.data},{form.password.data}\n")
        flash('Account created! You can now log in.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html', form=form)

@app.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        with open(USER_DATA_FILE, 'r') as f:
            users = f.readlines()
            for user in users:
                uid, username, password = user.strip().split(',')
                if username == form.username.data and password == form.password.data:
                    login_user(User(uid, username, password))
                    # 创建用户的记忆文件
                    memory_file = f'{username}_memory.json'
                    if not os.path.exists(memory_file):
                        with open(memory_file, 'w') as f:
                            f.write(json.dumps([]))
                    return redirect(url_for('chat'))
        flash('Login Unsuccessful. Please check username and password', 'danger')
    return render_template('login.html', form=form)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('home'))

system_memory_prompt = """Evaluate the following text and decide which text should be added to the memory.

[Output Format]
- Memory Text.
- Original text.
- Type:
- confidence (a number between 0% and 100%).

- Memory Text.
- Original Text.
- Type:
- confidence (a number between 0% and 100%).

...

[Rules]

MUST output memory text, original text, type, and confidence for each memory using the format above. 

Memory text refers to the key information that you infer the user wants you to remember from their prompt. 
This could be details such as their job title, the name of their company, the name of a project, etc.
Try to extract as many relevant pieces of information as possible. The Memory Text should be a concise summary of the key information.


Original text is the text from the user's original prompt from which the Memory Text was derived.
Correspond each piece of Memory Text with the Original Text from which it was inferred.

Type refers to the type of information that the Memory Text represents, for example, "职业信息", "地点信息", etc.
You need to prioritize using an existing memory_type: {}. If the current memoryText does not belong to any existing memory_type, only then should you use a new memory_type.

You could output nothing if there were no memories.
For confidence you should output a concrete number.
NEVER output any text I include in the output format such as 0% and 100%

Here are an example:
[Input]
帮我设计一份面试题库，候选人通常是中国985高校的CS方向的在读学生或者应届毕业生，我需要和他们一起开发类似腾讯的太极机器学习平台，Idex平台，US平台，以及亚马逊的SageMaker类似的东西，技术栈是Java，需要用到的Framework是SpringBoot，用到的ORM是 JPA
[Output]
- Memory Text. 你是中级技术经理
- Original Text. 机器学习平台，亚马逊，Java, SpringBoot, JPA
- Type: 职业信息
- confidence 91.5%

- Memory Text. 你在阿里云工作
- Original Text. 类似腾讯
- Type: 地点信息
- confidence 89.2%


Here is my Input:
[Input]
"""

# 用户这次输入+过往记忆-->GPT-->输出?
# @app.route('/info_extraction', methods=['POST'])
# @login_required
# def info_extraction():
#     message = request.form.get('message')
#     memory_type = request.form.get('memory_type')
#     with open(f"{current_user.username}_memory.json", "r") as f:
#         memory = json.loads(f.read())
    
#     response = client.chat.completions.create(
#         model="gpt-4o",
#         messages=[
#             {"role": "system", "content": system_memory_prompt.format(memory_type)},
#             {"role": "user", "content": message}
#         ]
#     )

@app.route('/memory_evaluation', methods=['POST'])
@login_required
def memory_evaluation():
    message = request.form.get('message')
    memory_type = request.form.get('memory_type') 
    print(f"Received message for evaluation: {message}")  # 调试信息

    # 使用 GPT 模型进行初步推理，判断需要存储到记忆的内容
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": system_memory_prompt.format(memory_type)},
            {"role": "user", "content": message}
        ]
    )
    # 假设 GPT 返回的内容是需要存入记忆的内容
    memory_suggestions = []
    raw_suggestions = response.choices[0].message.content.strip().split("\n\n")
    print(response.choices[0].message.content)
    for suggestion in raw_suggestions:
        parts = suggestion.split('- Original Text.')
        if len(parts) < 2:
            print("Warning: missing Original Text or confidence part.")
            continue

        memory_text = parts[0].replace("- Memory Text.", "").strip()
        original_text = parts[1].strip().split('- Type:')[0].strip()
        type_confidence = parts[1].strip().split('- Type:')[1].strip()
        type_info = type_confidence.strip().split('- confidence')[0].replace("\n", "")
        confidence = type_confidence.strip().split('- confidence')[1].replace("%", "")

        print(type_info)
        try:
            confidence = int(confidence)
        except ValueError:
            print(f"Invalid confidence value: {confidence}")
            confidence = 0  # 或者设置一个默认值

        memory_suggestions.append({
            'memoryText': memory_text,
            'originalText': original_text,
            'type': type_info,
            'confidence': confidence
        })

    print(f"Memory suggestions: {memory_suggestions}")  # 调试信息
    return jsonify({'memory_suggestions': memory_suggestions})

@app.route('/process_plugin', methods=['POST'])
@login_required
def process_plugin():
    phrase = request.form.get('phrase')
    action = request.form.get('action')

    # 调用函数保存或修改Memory
    save_memory(current_user.username, phrase, action)

    return jsonify({'status': 'success'})

MEMORY_DIR = 'memory'

@app.route("/get_memory", methods=['GET'])
@login_required
def get_memory():
    username = current_user.username
    with open(f"{username}_memory.json", "r") as f:
        memory = f.read()
    return jsonify({'memory': memory})

@app.route('/update_memory', methods=['GET', 'POST'])
@login_required
def update_memory():
    message = request.form.get('message')
    prompt = '''
    You need to extract explicit information provided by the user: Any explicit information that users tell you to remember. For example:

    The user's name, birthday, hobbies, and so on.
    Specific events, important dates, or projects.
    Personal preferences, such as favorite colors, foods, books, etc.
    Contextual information from the conversation: Sometimes, information that continuously appears in the conversation may also be recorded by you to help provide a more continuous conversational experience. For example:

    The project the user is dealing with or the course they are studying.
    Interests or concerns the user has recently mentioned.
    Criteria for judgement:

    Explicit remember request: When a user explicitly asks you to remember certain information, you prioritize recording it. For example, "Please remember my favorite book is '1984'".
    Continuity and relevance of the conversation: If certain information repeatedly appears in multiple conversations and is helpful in providing better answers, you might automatically remember this information.
    Importance and personal relevance: More important or personalized information, such as birthdays or important projects, are prioritized for recording.
    Updating Memories:

    Explicit user update request: Users can explicitly request to update information. For example, "My favorite book has changed to 'Brave New World'".
    Corrections in the conversation: If new information is provided in the conversation to correct previous information, you will update the record. For example, if you previously remembered that the user's favorite color is blue, but they later tell you they prefer green, you will update this information.
    Time-related information: Some information may need to be updated over time, such as the user's project progress or learning courses.
    
    Output Format:
    ['information ...',  '...', ...]

    MUST OBEY THE OUTPUT FORMAT.
    If there is no information to remember, please output an empty list.
    
    '''
    response = client.chat.completions.create(
        model="gpt-4o",
        messages = [
            {"role": "user", "content": message},
            {"role": "system", "content": prompt}
        ]
    )
    print("==================== MEMORY ================== \n")
    print(response.choices[0].message.content)
    print("============================================== \n")
    first_bracket = response.choices[0].message.content.find("[")
    last_bracket = response.choices[0].message.content.rfind("]")
    memory = response.choices[0].message.content[first_bracket:last_bracket+1]
    print("==================== MEMORY UPDATE ================== \n")
    print(memory)
    print("===================================================== \n")
    # 字符串变成数组
    if memory == "[]":
        return jsonify({'memory': []})
    import ast
    try:
        memory = ast.literal_eval(memory)
    except Exception as e:
        print(f"Error in parsing memory: {e}")
        memory = []

    previous_memory = []
    memory_list = []
    for mem in memory:
        memory_list.append({
            "id": generate_unique_id(),
            "memoryText": mem,
        })
    with open(f"{current_user.username}_memory.json", "r") as f:
        previous_memory = json.loads(f.read())
    
    # 数组合并
    merged_memory = previous_memory + memory_list
    print("======================================== \n")
    print(merged_memory)
    print("======================================== \n")
    # 没有动态merge了

    with open(f"{current_user.username}_memory.json", "w", encoding='utf-8') as f:
        f.write(json.dumps(merged_memory, ensure_ascii=False, indent=4))

    save_state_with_timestamp("updatememory")  # Save the state before processing
    return jsonify({'memory': merged_memory})

if not os.path.exists(MEMORY_DIR):
    os.makedirs(MEMORY_DIR)

def save_memory(user_id, phrase, action):
    memory_file = os.path.join(MEMORY_DIR, f'{user_id}_memory.txt')
    with open(memory_file, 'a') as f:
        if action == "add_memory":
            f.write(f"Memory added: {phrase}\n")
        elif action == "modify":
            f.write(f"Memory modified: {phrase}\n")


@app.route('/chatbot', methods=['POST'])
@login_required
def chatbot():
    chat_name = request.form.get('chat_name', '')
    message = request.form.get('message', '')
    new_chat_name = None

    # 如果 chat_name 为空，自动生成新的对话名称
    if not chat_name:
        new_chat_name = message[:10]  # 自动生成新的对话名称，截取前10个字符
        chat_name = new_chat_name
        chat_file = os.path.join(CHAT_DATA_DIR, f'{current_user.username}__{chat_name}.txt')

        # 如果文件不存在，说明这是一个新的对话，需要创建文件
        if not os.path.exists(chat_file):
            open(chat_file, 'w').close()

    with open(f"{current_user.username}_memory.json", "r") as f:
        memory = json.loads(f.read())
    
    memory_texts = [mem["memoryText"] for mem in memory]
    memory = "\n".join(memory_texts)

    if chat_name and message:
        chat_file = os.path.join(CHAT_DATA_DIR, f'{current_user.username}__{chat_name}.txt')
        log_message("user", message)
        save_message_to_file(chat_file, "user", message)
        current_chat_history = get_current_chat_history(chat_name)
        # 生成响应
        past_messages = [
            {"role": "system", "content": "Answer user's question with the following memories. You can use these memories to answer user's question: "+ memory}]+current_chat_history+[
            {"role": "user", "content": message},
        ]
        print("============== FOR DEBUG ============= \n")
        print(past_messages)
        print("====================================== \n")
        bot_response = generate_response(past_messages)
        print(f"Bot response: {bot_response}")
        log_message("assistant", bot_response)
        save_message_to_file(chat_file, "assistant", bot_response)

    save_state_with_timestamp("chatbot")  # Save the state before processing

    return jsonify({'response': bot_response, 'chat_name': chat_name})

@app.route('/chat', methods=['GET', 'POST'])
@login_required
def chat():
    chat_list = [f.split('__')[1].split(".")[0] for f in os.listdir(CHAT_DATA_DIR) if f.startswith(f"{current_user.username}__")]
    selected_chat = request.args.get('chat_name', '')

    if request.method == 'POST':
        new_chat_name = request.form.get('new_chat_name')
        if new_chat_name:
            # 创建新对话
            selected_chat = new_chat_name
            chat_file = os.path.join(CHAT_DATA_DIR, f'{current_user.username}__{selected_chat}.txt')
            if not os.path.exists(chat_file):
                open(chat_file, 'w').close()
            chat_list = [f.split('__')[1] for f in os.listdir(CHAT_DATA_DIR) if f.startswith(f"{current_user.username}__")]
        else:
            chat_name = request.form.get('chat_name', '')
            message = request.form.get('message', '')
            # with open(f"{current_user.username}_memory.json", "r") as f:
            #     memory = json.loads(f.read())
            try:
                with open(f"{current_user.username}_memory.json", 'r') as f:
                    memory = json.loads(f.read().strip())
            except json.JSONDecodeError as e:
                print(f"Error decoding JSON: {e}")
                memory = {}  # 或者其他默认行为


            memory = "\n".join(memory)
            if chat_name and message:
                chat_file = os.path.join(CHAT_DATA_DIR, f'{current_user.username}__{chat_name}.txt')
                log_message("user", message)
                save_message_to_file(chat_file, "user", message)
                current_chat_history = get_current_chat_history(chat_name)

                bot_response = generate_response([
                    {"role": "system", "content": "Answer user's question with the following memories. You can use these memories to answer user's question: " + memory}
                ] + current_chat_history + [
                    {"role": "user", "content": message},
                ])
                log_message("assistant", bot_response)
                save_message_to_file(chat_file, "assistant", bot_response)

                selected_chat = chat_name

    chat_file = os.path.join(CHAT_DATA_DIR, f'{current_user.username}__{selected_chat}.txt')
    conversations = []
    if os.path.exists(chat_file):
        with open(chat_file, 'r') as f:
            conversations = [json.loads(line.strip()) for line in f.readlines()]
            formatted_conversations = [{'message': conv['message']} for conv in conversations]
    else:
        formatted_conversations = []
    return render_template('chat.html', chat_list=chat_list, conversations=conversations, selected_chat=selected_chat)


@app.route('/get_privacy', methods=['POST'])
@login_required
def get_privacy():
    chat_name = request.form.get('chat_name', '')
    
    # Load memory from JSON file
    # with open(f'{current_user.username}_memory.json', 'r') as f:
    #     memory = json.loads(f.read())
    try:
        with open(f"{current_user.username}_memory.json", 'r') as f:
            memory = json.loads(f.read().strip())
    except json.JSONDecodeError as e:
        print(f"Error decoding JSON: {e}")
        memory = {}  # 或者其他默认行为

    
    # Ensure that the memory is in the correct format
    memory_list = []
    for mem in memory:
        if isinstance(mem, dict):
            memory_list.append({
                "id": mem.get("id"),
                "message": mem.get("memoryText")
            })
        else:
            # If mem is not a dict, assume it's a raw memory text and generate an ID
            memory_list.append({
                "id": generate_unique_id(),  # Ensure you have a function to generate unique IDs
                "message": mem
            })
    
    # Convert memory list to a string in JSON format for the prompt
    memory_str = json.dumps(memory_list)
    
    message = request.form.get('message')
    user_chat_history = get_user_only_chat_history(chat_name)
    print(" ========== FOR PRIVACY PROBING ============ \n")
    print(user_chat_history)
    print(memory_str)
    print(" ========== FOR PRIVACY PROBING ============ \n")

    prompt = '''
1. Please review the following text and decide if it can infer any personal sensitive information.
The text consists of the past inputs and the memory. 
The information stored in the memory should not be classified as personal or sensitive. 
Only consider information that inferred from the past inputs and the memory. 
2. If any personal or sensitive information is inferred, please identify the information, indicate the exact phrases or words from the past input and the orginal entire sentences from the memory used for the inference.
3. indicate both extracted words and the original entire sentence. 
4. Additionally, provide your associated confidence level of making this inference: how sure are you in inferring? 
5. Also provide the type of the inferred private information according to the ``Private Data Type''.
6. Copy the id of the input corresponidngto the text to the id in the output.

Private Data Type:
Personal basic information: consists of name, date of birth, age, gender, ethnicity, nationality, place of origin, marital status, family relationships, address, phone number, email address, hobbies and interests
Personal identity Information: consists of identity card, passport, driver's license, work ID
Online Identity Identifier Information: consists of user account, user ID, instant messaging account, social media account, nickname, IP address
Personal Health Status and Physiological Information: consists of weight, height, blood type, medical conditions, prescription, medical test reports, physical examination reports, medical history
Personal Education and Work Information: consists of education level, degree, education history, transcript, occupation, job title, employer, work location, work experience, salary, resume.
Personal Financial Information: consists of bank card number, payment account, account balance, transaction orders, transaction account, payment records, income status, property information, savings information, vehicle information, tax amount, virtual assets
Personal Borrowing Information: consists of loan information, repayment information, debt information, credit record, credit report
Identity Authentication Information: account login password, bank card password, payment password, account query password, transaction password, bank card security code, USB key, dynamic password, SMS verification code, personal digital certificate, random token
Personal Communication Information: communication records, text messages, emails, instant messaging
Contact Information: address book, friends list, group list, email address list, family relationships, work relationships, social relationships
Personal Internet Records: web browsing history, software usage records, cookies, published social media information, search history, download history
Personal Location Information: area code, city code, latitude and longitude, accomodation information, community code
Personal Movement Information: step count, step frequency, exercise duration, exercise distance, exercise type, heart rate during exerciese
Other Personal Information: sexual orientation.

Rules:
- MUST follow ``Private Data Type''.
- NEVER output unuseful other text of other form.
- MUST use the id in the input to fill the output.     
- NEVER output repetitive or same privacy info.

Input Format:
    - Past Inputs: ...
    - Memory: ...

Output Format:
    [{
        "privacy_info": ...,
        "confidence": ...,
        "type": ...,
        "used_user_input": [
            "...", "...", ...
        ],
        "used_memory": [
            "...", "...", ...
        ]
    },{
        "privacy_info": ...,
        "confidence": ...,
        "type": ...,
        "used_user_input": [
            "...", "...", ...
        ],
        "used_memory": [
            "...", "...", ...
        ]
    }]


Example:
    Input:
        - Past Inputs: [{"id":"5d2bf23c-9ea7-4917-804e-dcd106d365b1","message":"Please plan me a two day and one night trip to Pune by car"}]
        - Memory: [{"id":"b13d67ec-20e8-49f8-aaf5-1a67cbfa7c26","message":"User watches Bollywood movies all the time"}]

    Output:
        [{
            "privacy_info": "The user is Indian.",
            "confidence": "95%",
            "type": "Personal Basic Information",
            "used_user_input": [
                {
                    "id":"5d2bf23c-9ea7-4917-804e-dcd106d365b1",
                    "shortened":"trip to Pune",
                    "full":"Please plan me a two day and one night trip to Pune by car",
                }
            ],
            "used_memory": [
                {
                    "id":"b13d67ec-20e8-49f8-aaf5-1a67cbfa7c26",
                    "shortened": "watches Bollywood movies",
                    "full": "User watches Bollywood movies all the time.",
                }
            ]
        }]

The following is the input: '''
    prompt += f"- Past Input: {user_chat_history}\n"
    prompt += f"- Memory: {memory}\n"
    prompt += "Please output the privacy_info, confidence, used_user_input, and used_memory."
    print("================================ \n")
    print(prompt)
    print("================================ \n")
    response = client.chat.completions.create(
        model="gpt-4o",
        messages = [
            {"role": "user", "content": prompt}
        ]

    )
    # 解析成json
    privacy = response.choices[0].message.content
    
    with open(f"{current_user.username}_privacy.json", "a") as f:
        f.write("=======================================\n")
        f.write(str(time.time()) + "\n")
        f.write(str(privacy) + "\n")
        f.write("=======================================\n")

    first_bracket = privacy.find("[")   
    last_bracket = privacy.rfind("]")
    privacy = privacy[first_bracket:last_bracket+1]

    # text to json
    try:
        privacy = json.loads(privacy)
    except:
        traceback.print_exc()
        privacy = {}
        pass

    save_state_with_timestamp("getprivacy")  # Save the state before processing
    print(" ============== PRIVACY ============== \n")
    print(privacy)
    print(" ============== PRIVACY ============== \n")
    return jsonify({'privacy': privacy})

@app.route('/delete_memory', methods=['POST'])
@login_required
def delete_memory():
    memory = request.form.get('memory')
    with open(f"{current_user.username}_memory.json", "r") as f:
        memoryList = json.loads(f.read())
    memoryList.remove(memory)
    with open(f"{current_user.username}_memory.json", "w", encoding='utf-8') as f:
        f.write(json.dumps(memoryList, ensure_ascii=False, indent=4))

    print("Processing chat message")
    chat_name = request.form.get('chat_name', '')
    message = request.form.get('message', '')
    
    memory_item = '\n'.join(memoryList)
    print(memory_item)
    chat_file = os.path.join(CHAT_DATA_DIR, f'{current_user.username}__{chat_name}.txt')
    log_message("user", message)
    save_message_to_file(chat_file, "user", message)

    # 生成响应
    bot_response = generate_response([
        {"role": "system", "content": "Answer user's question with the following memories."},
        {"role": "user", "content": message},
        {"role": "assistant", "content": "You can use these memories to answer user's question: "+memory_item}
    ])
    print(f"Bot response: {bot_response}")
    log_message("assistant", bot_response)
    save_message_to_file(chat_file, "assistant", bot_response)

    return jsonify({'response': bot_response})
    

@app.route('/clear', methods=['POST'])
@login_required
def clear_history():
    selected_chat = request.form.get('chat_name', '')
    chat_file = os.path.join(CHAT_DATA_DIR, f'{selected_chat}.txt')
    if os.path.exists(chat_file):
        os.remove(chat_file)
    session['history'] = []
    return jsonify({'status': 'history cleared'})

def generate_response(history):
    # 调用Azure OpenAI的API生成响应
    deployment_name = "gpt-4o"  # 替换为你的实际部署名称
    response = client.chat.completions.create(
        model=deployment_name,
        messages=history,
        stream=False  # 设为False以获得完整响应
    )
    
    # 记录查询日志
    log_query(history, response.choices[0].message.content.strip())
    
    return response.choices[0].message.content.strip()

def get_user_only_chat_history(chat_name):
    chat_file = os.path.join(CHAT_DATA_DIR, f'{current_user.username}__{chat_name}.txt')
    user_only_history = []

    if (os.path.exists(chat_file)):
        with open(chat_file, 'r') as f:
            chat_history = f.readlines()
            for i, line in enumerate(chat_history):
                chat_entry = json.loads(line.strip())
                if chat_entry['role'] == 'user':
                    # Append each message as a dictionary with a unique ID
                    user_only_history.append({
                        "id": chat_entry['id'],  # Unique ID for each user input
                        "message": chat_entry['message']
                    })

    return user_only_history

def save_message_to_file(chat_file, role, message):
    with open(chat_file, 'a') as f:
        message_entry = {
            'id': generate_unique_id(),
            'role': role,
            'message': message
        }
        f.write(json.dumps(message_entry) + '\n')

def get_current_chat_history(chat_name):
    chat_file = os.path.join(CHAT_DATA_DIR, f'{current_user.username}__{chat_name}.txt')
    chat_history = []
    if os.path.exists(chat_file):
        with open(chat_file, 'r') as f:
            for line in f:
                chat_history.append(json.loads(line.strip()))
    # rename 'message' field in chat history to 'content' field
    new_chat_history = []
    for chat in chat_history:
        new_chat_history.append({
            'role': chat['role'],
            'content': chat['message'],
        })
    return new_chat_history

# deprecated
def read_chat_history(user_id):
    chat_history = []
    chat_files = [f for f in os.listdir(CHAT_DATA_DIR) if f.startswith(f"{user_id}__")]
    for chat_file in chat_files:
        with open(os.path.join(CHAT_DATA_DIR, chat_file), 'r') as f:
            for line in f:
                chat_history.append(json.loads(line.strip()))
    return chat_history

def log_message(role, message):
    timestamp = datetime.now().isoformat()
    log_entry = {
        'timestamp': timestamp,
        'role': role,
        'message': message
    }
    
    # 使用当前用户的用户名作为日志文件的目录名称
    user_log_dir = os.path.join(CHAT_DATA_DIR, current_user.username)
    if not os.path.exists(user_log_dir):
        os.makedirs(user_log_dir)

    with open(os.path.join(user_log_dir, "logging_with_time.log"), "a") as f:
        f.write("[LOG]: \n")
        f.write(str(log_entry) + "\n")
        f.write("=============================\n")

def log_query(history, response):
    # 使用当前用户的用户名作为日志文件的目录名称
    user_log_dir = os.path.join(CHAT_DATA_DIR, current_user.username)
    if not os.path.exists(user_log_dir):
        os.makedirs(user_log_dir)

    with open(os.path.join(user_log_dir, "gpt_query.log"), "a+") as f:
        f.write(str(time.time()) + "\n")
        for hh in history:
            f.write(str(hh) + "\n")
        f.write(response + "\n")
        f.write("======================================== query \n")

@app.route('/submit_changes', methods=['POST'])
@login_required
def submit_changes():
    data = request.json
    changes = data.get('changes')

    save_state_with_timestamp("submitchanges")  # Save the state before processing

    # Load memory from file
    with open(f"{current_user.username}_memory.json", "r") as f:
        memory_list = json.loads(f.read())

    # Load user chat history from the relevant chat file
    chat_name = data.get('chat_name', '')
    chat_file = os.path.join(CHAT_DATA_DIR, f'{current_user.username}__{chat_name}.txt')

    # Read the chat history
    if os.path.exists(chat_file):
        with open(chat_file, 'r') as f:
            chat_history = [json.loads(line.strip()) for line in f.readlines()]
    else:
        chat_history = []

    # Process each change
    for change in changes:
        change_id = change.get('id')
        new_text = change.get('newText')

        # Update the corresponding memory based on the ID
        for memory_item in memory_list:
            if memory_item['id'] == change_id:
                memory_item['memoryText'] = new_text
                break

        # Update the corresponding user input based on the ID
        for chat_entry in chat_history:
            if chat_entry.get('id') == change_id:
                chat_entry['message'] = new_text
                break

    # Save the updated memory back to the memory file
    with open(f"{current_user.username}_memory.json", "w", encoding='utf-8') as f:
        f.write(json.dumps(memory_list, ensure_ascii=False, indent=4))

    # Save the updated chat history back to the chat file
    with open(chat_file, 'w', encoding='utf-8') as f:
        for chat_entry in chat_history:
            f.write(json.dumps(chat_entry) + '\n')

    # Trigger a re-render on the frontend (e.g., by returning the updated chat history and memory)
    updated_data = {
        'status': 'success',
        'updated_memory': memory_list,
        'updated_chat_history': chat_history
    }

    return jsonify(updated_data)

def merge_memories(existing_memories, new_memories):
    """
    Merge two lists of memory dictionaries, removing duplicates based on the 'memoryText' field.
    """
    merged_memories = existing_memories.copy()  # Start with the existing memories
    memory_texts = {mem["memoryText"] for mem in existing_memories}  # Track the memoryText we've seen
    
    for mem in new_memories:
        if mem["memoryText"] not in memory_texts:
            merged_memories.append(mem)
            memory_texts.add(mem["memoryText"])  # Ensure this memoryText is marked as seen
    
    save_state_with_timestamp("submitchanges")  # Save the state before processing

    return merged_memories

def save_state_with_timestamp(state_name):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    state_dir = os.path.join(CHAT_DATA_DIR, current_user.username, "state_logs")

    if not os.path.exists(state_dir):
        os.makedirs(state_dir)

    # Load memory
    with open(f"{current_user.username}_memory.json", "r") as f:
        memory = json.loads(f.read())

    # Save memory with timestamp
    memory_filename = os.path.join(state_dir, f"memory_{state_name}_{timestamp}.json")
    with open(memory_filename, "w", encoding='utf-8') as f:
        json.dump(memory, f, ensure_ascii=False, indent=4)

    # Save chat history with timestamp for all chats
    for chat_name in [f.split('__')[1].split(".")[0] for f in os.listdir(CHAT_DATA_DIR) if f.startswith(f"{current_user.username}__")]:
        chat_file = os.path.join(CHAT_DATA_DIR, f'{current_user.username}__{chat_name}.txt')
        if os.path.exists(chat_file):
            try:
                with open(chat_file, 'r') as f:
                    chat_history = [json.loads(line.strip()) for line in f.readlines()]
                chat_filename = os.path.join(state_dir, f"chat_{chat_name}_{state_name}_{timestamp}.json")
                with open(chat_filename, "w", encoding='utf-8') as f:
                    json.dump(chat_history, f, ensure_ascii=False, indent=4)
            except:
                traceback.print_exc()
                pass

@app.route('/api/messages/update', methods=['POST'])
@login_required
def update_message():
    data = request.json
    message_id = data.get('id')
    new_text = data.get('text').strip("Save Cancel").strip("\n")
    selected_chat = data.get('chat_name')  # 从前端获取 selected_chat
    print(selected_chat, message_id, new_text)
    if not message_id or not new_text or not selected_chat:
        return jsonify({'status': 'failure', 'message': 'Invalid data.'}), 400

    # 假设消息是存储在用户特定聊天记录的文本文件中
    chat_file = os.path.join(CHAT_DATA_DIR, f'{current_user.username}__{selected_chat}.txt')
    
    if not os.path.exists(chat_file):
        return jsonify({'status': 'failure', 'message': 'Chat file not found.'}), 404

    # 读取现有的对话记录
    with open(chat_file, 'r') as f:
        conversations = f.readlines()
    message_id = eval(message_id)
    # print(message_id, len
    if message_id > len(conversations):
        return jsonify({'status': 'failure', 'message': 'Invalid message ID.'}), 400

    # 更新指定的消息
    # role, _ = conversations[message_id-1].split(': ', 1)
    # ipdb.set_trace()
    # print(role, new_text)
    # ipdb.set_trace()
    # updated_message = f"{role}: {new_text}\n"
    print(conversations[message_id-1])
    json_record = json.loads(conversations[message_id-1])
    json_record['message'] = new_text
    conversations[message_id-1] = json.dumps(json_record) + "\n"
    print(conversations[message_id-1])
    # 保存更新后的对话记录
    with open(chat_file, 'w') as f:
        f.writelines(conversations)

    return jsonify({'status': 'success', 'message': 'Message updated successfully.'})


if __name__ == '__main__':
    if not os.path.exists(USER_DATA_FILE):
        open(USER_DATA_FILE, 'w').close()
    app.run(debug=True, host='0.0.0.0', port=5005)
