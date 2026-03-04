"""
LLMHelper – wraps all LLM calls in one place.

Every method takes plain strings and returns a plain Python value so the
rest of the app never has to touch LangChain objects directly.
"""

from typing import Optional, Tuple

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

from config import LLM_MODEL, LLM_TEMPERATURE, PAGE_CONFIG


class LLMHelper:
    def __init__(self):
        self._llm = ChatOpenAI(model=LLM_MODEL, temperature=LLM_TEMPERATURE)

    def evaluate_proceed(
        self, user_input: str, action_context: str, robot_message: str = ""
    ) -> Tuple[bool, Optional[str]]:
        """
        Classify user intent and generate a response if they are not ready.
        Returns (should_proceed, follow_up_message_or_None).
        """
        robot_context = (
            f"The robot just said:\n  \"{robot_message}\"\n\n"
            if robot_message else ""
        )
        messages = [
            SystemMessage(
                content=(
                    "You are a friendly digital health assistant.\n"
                    f"{robot_context}"
                    f"The user was being asked to: {action_context}\n\n"
                    "Decide whether the user's response is POSITIVE or NEGATIVE in sentiment.\n"
                    "A positive response means they are willing, ready, agreeing, or consenting.\n"
                    "Examples of positive responses include the words 'start', 'continue', 'proceed', 'I agree', 'I accept', 'yes'.\n"
                    "Use common sense reasoning about whether they are ready.\n"
                    "A negative response means they are unwilling, confused, asking a question,\n"
                    "or explicitly declining.\n\n"
                    "OUTPUT RULES:\n"
                    "- If positive: reply with ONLY the single word: PROCEED\n"
                    "- If negative: if the user is asking a question or making a comment which is relevant to the health screening,\n"
                    "  briefly assist them, then gently remind them about the current step.\n"
                    "  Do NOT begin your response with the word PROCEED."
                )
            ),
            HumanMessage(content=f"User said: {user_input}"),
        ]
        response = self._llm.invoke(messages)
        text = response.content.strip()
        if text.upper() == "PROCEED":
            return True, None
        return False, text

    def evaluate_questionnaire_input(
        self, user_input: str, question_key: str, question_text: str = ""
    ) -> Tuple[str, Optional[str]]:
        """
        Determine if the user is skipping, answering, or needs a follow-up.
        Returns ("skip", None) | ("answer", matched_option) | ("followup", message).
        """
        options = PAGE_CONFIG[question_key]["options"]
        options_text = "\n".join(f"  {i+1}. {o}" for i, o in enumerate(options))
        question_context = f"The question: \"{question_text}\"\n\n" if question_text else ""
        messages = [
            SystemMessage(
                content=(
                    "You are Temi, a friendly digital health assistant, processing a "
                    "user's response to a health questionnaire question.\n"
                    f"{question_context}"
                    f"The answer options are:\n{options_text}\n\n"
                    "Determine what the user intends:\n\n"
                    "1. SKIP — they want to skip (indicators: skip, pass, next, move on,\n"
                    "   I'd rather not, prefer not to say, no thanks, not sure, etc.)\n"
                    "2. ANSWER — their response maps to one of the options above\n"
                    "   (by number, keyword, or meaning — e.g. \"I smoke on the weekend\"\n"
                    "   → \"Occasionally\", \"I exercise every day\" → \"Daily\",\n"
                    "   \"I drink like a fish\" → \"More than 21 units\")\n"
                    "3. FOLLOWUP — the user said something that doesn't clearly match\n"
                    "   an option. This includes: vague answers that mention a relevant\n"
                    "   topic but not enough detail (e.g. \"I do zumba\" without frequency),\n"
                    "   clarification questions (e.g. \"do you mean cigarettes or vapes?\"),\n"
                    "   off-topic remarks, or genuinely unmatchable input.\n\n"
                    "OUTPUT RULES:\n"
                    "- If SKIP: reply with only the word SKIP\n"
                    "- If ANSWER: reply with only the exact matching option text from the list\n"
                    "- If FOLLOWUP: reply with FOLLOWUP: followed by a friendly 1-2 sentence\n"
                    "  response as Temi that acknowledges what the user said, then guides\n"
                    "  them toward choosing one of the answer options. You can say 'skip'\n"
                    "  to move on."
                )
            ),
            HumanMessage(content=f"User said: {user_input}"),
        ]
        response = self._llm.invoke(messages)
        result = response.content.strip()
        upper = result.upper()
        if upper == "SKIP":
            return "skip", None
        if result.upper().startswith("FOLLOWUP:"):
            message = result[len("FOLLOWUP:"):].strip()
            return "followup", message
        for opt in options:
            if opt.lower() in result.lower() or result.lower() in opt.lower():
                return "answer", opt
        # Safety fallback: if LLM didn't follow format, treat as followup
        return "followup", None

    def retry_or_give_up(self, user_input: str) -> bool:
        """
        Return True if the user wants to retry a failed device reading,
        False if they want to stop and return to idle.
        """
        messages = [
            SystemMessage(
                content=(
                    "The user was asked whether they want to retry a failed device reading "
                    "or give up and finish the session.\n"
                    "Reply with ONLY 'RETRY' if they want to try again, "
                    "or 'GIVEUP' if they want to stop."
                )
            ),
            HumanMessage(content=f"User said: {user_input}"),
        ]
        response = self._llm.invoke(messages)
        return "RETRY" in response.content.upper()

