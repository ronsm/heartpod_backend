# LangChain Stateful Conversation POCs

Two proof-of-concept implementations demonstrating stateful human-robot conversations using LangChain. The scenario: a health monitoring robot guides users through four sensor readings (heart rate, weight, blood pressure, temperature) using natural language interaction.

## POCs Included

### 1. Simple Python State Machine (`langtest_simple.py`)
- **Approach**: Manual state tracking using a Python class
- **Pros**: Easy to understand, minimal dependencies, straightforward control flow
- **Cons**: More manual state management code

### 2. LangGraph (`langtest_langgraph.py`)
- **Approach**: Graph-based state management using LangGraph
- **Pros**: More sophisticated, follows modern LangChain patterns, easier to extend
- **Cons**: Additional dependency, slightly more complex setup

## Features

Both POCs include:
- **LLM-based intent detection**: The system uses GPT to understand when users want to proceed (not keyword-based)
- **Simulated sensor readings**: Generates realistic random health data
- **Off-topic handling**: Users can ask questions without disrupting the flow
- **Natural conversation**: No rigid command structure required

## Setup

1. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Set your OpenAI API key** (if not already in environment):
   ```bash
   export OPENAI_API_KEY='your-api-key-here'
   ```

## Usage

### Run the Simple State Machine POC:
```bash
python langtest_simple.py
```

### Run the LangGraph POC:
```bash
python langtest_langgraph.py
```

## Example Interaction

```
Robot: Hello! I'm here to help you take some health readings today.
       We'll measure your heart rate, weight, blood pressure, and
       temperature. Are you ready to begin?

You: What will this take?

Robot: This will only take a few minutes! We'll go through four quick
       sensor readings. Are you ready to start with your heart rate?

You: yes let's do it

Robot: Great! Let's start with your heart rate. Please place your
       finger on the sensor.

  [Sensor is reading...]
  [Reading complete: 72]

Robot: Excellent! Next, let's measure your weight. Please step onto
       the scale.

You: ok

  [Sensor is reading...]
  [Reading complete: 68.4]

... (continues through all sensors)

Robot: All done! Here are your readings:
  - Heart Rate: 72
  - Weight: 68.4
  - Blood Pressure: 125/82
  - Temperature: 36.8

Thank you for completing your health check!
```

## How It Works

### Intent Detection
Both POCs use the LLM to analyze user input and determine if they're ready to proceed. The system recognizes various ways of expressing readiness:
- Direct: "yes", "ok", "ready"
- Casual: "let's go", "sure", "sounds good"
- Implied: "I'm ready", "let's do it"

### State Flow
1. **Greeting** → Introduce the process
2. **Heart Rate** → Take first reading
3. **Weight** → Take second reading
4. **Blood Pressure** → Take third reading
5. **Temperature** → Take final reading
6. **Complete** → Show all results

### Sensor Simulation
Realistic random values:
- Heart rate: 60-100 bpm
- Weight: 50-100 kg
- Blood pressure: 110-140 / 70-90 mmHg
- Temperature: 36.5-37.5°C

## Architecture Comparison

| Feature | Simple State Machine | LangGraph |
|---------|---------------------|-----------|
| State Management | Manual class variable | Graph nodes & edges |
| Extensibility | Requires code changes | Add nodes & edges |
| Code Complexity | Lower | Moderate |
| LangChain Integration | Basic | Deep |
| Best For | Quick POCs, learning | Production, complex flows |

## Exiting
Type `quit` or `exit` at any prompt to end the conversation.

## Notes
- The LLM calls are used for intent detection and handling off-topic questions
- Sensor readings are simulated with random data (no actual hardware needed)
- Both POCs use GPT-3.5-turbo for cost efficiency
- The conversation state persists throughout the session
