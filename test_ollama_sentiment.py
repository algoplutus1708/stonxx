import ollama
import re

def get_market_sentiment(headlines, model_name='llama3'):
    """
    Passes headlines to local Ollama instance and extracts a sentiment score between -1.0 and 1.0.
    """
    prompt = f"""Role: Expert Indian Stock Market Quantitative Analyst.
Task: Analyze the provided headlines and rate the macroeconomic sentiment on a strict scale from -1.0 (extreme panic/bearish) to 1.0 (extreme euphoria/bullish). 0.0 is neutral.
Constraint: Respond WITH ONLY THE NUMBER. Do not include text.

Headlines:
{headlines}
"""

    try:
        response = ollama.chat(model=model_name, messages=[
            {
                'role': 'user',
                'content': prompt,
            },
        ])
        
        raw_output = response['message']['content'].strip()
        
        # Regex to extract any floating point or integer number
        match = re.search(r'-?\d+\.?\d*', raw_output)
        
        if match:
            score = float(match.group())
            # Bound the score between -1.0 and 1.0
            return max(-1.0, min(1.0, score))
        else:
            print(f"Could not parse a number from output: {raw_output}")
            return 0.0
            
    except Exception as e:
        print(f"Error connecting to Ollama or processing sentiment: {e}")
        return 0.0

if __name__ == "__main__":
    bullish_news = "India GDP growth smashes expectations, hits 8.4% in Q3. FIIs inject record $2 Billion into Indian equities."
    bearish_news = "Global markets crash 4% amidst new geopolitical tensions. Major Indian bank reports massive unexpected loan defaults."
    
    # We use llama3 by default, you may change it to 'mistral' or any downloaded model.
    # We will test mistral just in case llama3 isn't available, or rely on what's installed.
    # To see installed models, you can run `ollama list` in your terminal.
    target_model = 'llama3.2'
    
    print(f"Testing Sentiments with model '{target_model}'...")
    
    print(f"\n--- Bullish Scenario ---")
    print(f"News: {bullish_news}")
    bullish_score = get_market_sentiment(bullish_news, model_name=target_model)
    print(f"Bullish Score: {bullish_score}")
    
    print(f"\n--- Bearish Scenario ---")
    print(f"News: {bearish_news}")
    bearish_score = get_market_sentiment(bearish_news, model_name=target_model)
    print(f"Bearish Score: {bearish_score}")
