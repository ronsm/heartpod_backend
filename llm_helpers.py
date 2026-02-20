"""
LLMHelper – wraps all LLM calls in one place.

Every method takes plain strings and returns a plain Python value so the
rest of the app never has to touch LangChain objects directly.
"""

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

from config import LLM_MODEL, LLM_TEMPERATURE, PAGE_CONFIG


class LLMHelper:
    def __init__(self):
        self.llm = ChatOpenAI(model=LLM_MODEL, temperature=LLM_TEMPERATURE)

    # ------------------------------------------------------------------
    # Conversation flow helpers
    # ------------------------------------------------------------------

    def should_proceed(self, user_input: str, action_context: str) -> bool:
        """Return True if the user is confirming they are ready / consenting."""
        messages = [
            SystemMessage(
                content=(
                    f"You are analysing user input in a health sensor conversation.\n"
                    f"The user was asked to complete this action: {action_context}\n\n"
                    "Determine if the user is indicating they are READY or CONSENTING to proceed.\n"
                    "They ARE ready/consenting if they:\n"
                    "- Say yes, ready, ok, sure, go ahead, let's go, done, continue, begin, start, etc.\n"
                    "- State they've completed the requested action.\n"
                    "- Say 'start self-screening'.\n"
                    "- State that they agree or accept.\n"
                    "Do not be too fussy distinguishing between 'ready' and 'continue'.\n"
                    "They are NOT ready if they are asking a question, requesting help, or declining.\n\n"
                    "Respond with ONLY 'YES' or 'NO'."
                )
            ),
            HumanMessage(
                content=f"User said: {user_input}\n\nAre they ready/consenting? (YES/NO)"
            ),
        ]
        response = self.llm.invoke(messages)
        return "YES" in response.content.upper()

    def handle_general_question(self, user_input: str, action_context: str) -> str:
        """
        Respond to an off-topic comment or question while keeping the
        conversation anchored to the current step.
        """
        messages = [
            SystemMessage(
                content=(
                    "You are Temi, a friendly digital health assistant.\n"
                    f"Current context: {action_context}\n\n"
                    "The user said something that isn't a direct confirmation to proceed. "
                    "Answer their question or respond to their comment helpfully and briefly, "
                    "then gently remind them about the current task. "
                    "Keep your response concise (2-3 sentences max)."
                )
            ),
            HumanMessage(content=user_input),
        ]
        response = self.llm.invoke(messages)
        return response.content

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
        response = self.llm.invoke(messages)
        return "RETRY" in response.content.upper()

    # ------------------------------------------------------------------
    # Questionnaire helpers
    # ------------------------------------------------------------------

    def user_wants_to_skip(self, user_input: str) -> bool:
        """Return True if the user wants to skip the current question."""
        messages = [
            SystemMessage(
                content=(
                    "The user is answering a health questionnaire question and may choose to skip it.\n"
                    "Did they indicate they want to skip? "
                    "Skip indicators include: 'skip', 'pass', 'next', \"I'd rather not\", "
                    "'prefer not to say', 'no thanks', 'move on', etc.\n"
                    "Respond with ONLY 'YES' if they want to skip, "
                    "or 'NO' if they are attempting to answer."
                )
            ),
            HumanMessage(content=f"User said: {user_input}"),
        ]
        response = self.llm.invoke(messages)
        return "YES" in response.content.upper()

    def validate_answer(self, user_input: str, question_key: str):
        """
        Map the user's free-text answer to one of the predefined options for
        `question_key` (e.g. "q1"). Returns the matched option string, or None
        if the answer is ambiguous or doesn't match any option.
        """
        options = PAGE_CONFIG[question_key]["options"]
        options_text = "\n".join(f"  {i+1}. {o}" for i, o in enumerate(options))
        messages = [
            SystemMessage(
                content=(
                    "You are matching a user's free-text answer to the closest option "
                    "from a fixed list.\n"
                    f"The options are:\n{options_text}\n\n"
                    "If the user's answer clearly maps to one of these options "
                    "(by number, keyword, or meaning), reply with ONLY the exact option text.\n"
                    "If the answer is ambiguous, off-topic, or does not match any option, "
                    "reply with ONLY the word NONE."
                )
            ),
            HumanMessage(content=f"User said: {user_input}"),
        ]
        response = self.llm.invoke(messages)
        result = response.content.strip()
        if result.upper() == "NONE":
            return None
        for opt in options:
            if opt.lower() in result.lower() or result.lower() in opt.lower():
                return opt
        return None
