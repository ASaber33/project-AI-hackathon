# -*- coding: utf-8 -*-
"""
محاكاة اختبار نظام الأسئلة الطبية RAG
Test simulation for medical Q&A RAG system
"""

import os
os.environ['TF_ENABLE_ONEDNN_OPTS'] = '0'
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'

from rag import health, build_index, search_guidelines, build_context
from groq import Groq
from dotenv import load_dotenv
from pathlib import Path

# Load environment
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# Initialize Groq client
client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# =========================================================
# TEST QUESTIONS - أسئلة تجريبية
# =========================================================

test_questions = [
    "ما هي أعراض السكري من النوع الثاني؟",
    "كيف يتم علاج ارتفاع ضغط الدم؟",
    "ما هي أفضل طريقة للوقاية من السكتة الدماغية؟",
    "What are the symptoms of diabetes?",
    "How to treat hypertension?",
    "Prevention methods for heart disease?",
]

def print_separator(title=""):
    """طباعة فاصل"""
    print("\n" + "="*70)
    if title:
        print(f"  {title}")
        print("="*70)

def test_health():
    """اختبار صحة النظام"""
    print_separator("🔍 فحص صحة النظام | System Health Check")
    try:
        health_info = health()
        print(f"✅ PDFs: {health_info['pdf_count']} files")
        print(f"   Files: {', '.join(health_info['pdfs'])}")
        print(f"✅ Qdrant: {'Connected' if health_info['qdrant'] else 'Not connected'}")
        print(f"✅ Vector points: {health_info['points']}")
        return health_info
    except Exception as e:
        print(f"❌ Error: {e}")
        return None

def test_build_index():
    """بناء الفهرس"""
    print_separator("🔨 بناء الفهرس | Building Index")
    try:
        points = build_index()
        print(f"✅ Index built successfully!")
        print(f"   Total vectors: {points}")
        return points
    except Exception as e:
        print(f"❌ Error building index: {e}")
        return None

def test_search_and_answer(question):
    """البحث والإجابة على سؤال"""
    print_separator(f"❓ السؤال | Question: {question}")
    
    try:
        # البحث عن المستندات المرتبطة
        print("\n🔎 البحث عن المستندات ذات الصلة...")
        results = search_guidelines(question, top_k=3)
        
        if not results:
            print("❌ لم يتم العثور على نتائج")
            return
        
        print(f"✅ تم العثور على {len(results)} نتائج:")
        for i, result in enumerate(results, 1):
            print(f"\n   [{i}] من {result['source']} - الصفحة {result['page']}")
            print(f"       Score: {result.get('score', 'N/A')}")
            print(f"       Preview: {result['text'][:150]}...")
        
        # بناء السياق
        context = build_context(results)
        
        # طلب الإجابة من Groq
        print("\n🤖 جاري الحصول على الإجابة من الذكاء الاصطناعي...")
        
        system_prompt = """أنت مساعد طبي ذكي متخصص. 
استخدم المعلومات المقدمة من المستندات الطبية الموثوقة للإجابة على الأسئلة.
كن دقيقًا وأذكر المصدر عند الإمكان."""
        
        user_prompt = f"""السؤال: {question}

المعلومات من المستندات:
{context}

الرجاء تقديم إجابة دقيقة وموثوقة بناءً على المعلومات المقدمة."""
        
        response = client.messages.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            max_tokens=1024,
            temperature=0.7
        )
        
        answer = response.content[0].text
        print(f"\n✅ الإجابة | Answer:\n{answer}")
        
    except Exception as e:
        print(f"❌ Error: {e}")

def main():
    """البرنامج الرئيسي"""
    print("\n" + "🏥 " * 20)
    print("محاكاة نظام الأسئلة الطبية | Medical Q&A Simulation System")
    print("🏥 " * 20)
    
    # 1. فحص الصحة
    health_info = test_health()
    if not health_info:
        print("\n❌ لا يمكن المتابعة - تحقق من الاتصال")
        return
    
    # 2. بناء الفهرس (إذا لم يكن موجوداً)
    if health_info['points'] == 0:
        print("\n⏳ الفهرس فارغ - جاري البناء...")
        test_build_index()
    
    # 3. اختبار الأسئلة
    print("\n" + "="*70)
    print("🎯 بدء محاكاة الأسئلة | Starting Question Simulation")
    print("="*70)
    
    for i, question in enumerate(test_questions, 1):
        print(f"\n\n📌 السؤال {i}/{len(test_questions)}")
        test_search_and_answer(question)
        
        if i < len(test_questions):
            input("\n⏸️  اضغط Enter للمتابعة إلى السؤال التالي... (Press Enter to continue)")
    
    print("\n" + "="*70)
    print("✅ انتهت المحاكاة | Simulation Complete!")
    print("="*70)

if __name__ == "__main__":
    main()
