import logging
from fastapi import APIRouter, HTTPException
from models.schemas import GraphRefreshRequest, KnowledgeContextRequest, CourseRecommendationRequest
from services.terpai import bridge
from services.gemini import build_knowledge_document, generate_json_fallback
from services.catalog_service import catalog_service
from prompts.graph_analysis import build_graph_analysis_prompt
from prompts.topic_knowledge import build_topic_knowledge_prompt
from prompts.course_recommendation import (
    build_course_recommendation_prompt,
    build_recommendation_json_prompt,
)

try:
    from data.courses import COURSES
    from data.assignments import ASSIGNMENTS
    from data.notes import NOTES
    from data.concepts import CONCEPTS
    from data.connections import CONNECTIONS
except ImportError:
    COURSES = []
    ASSIGNMENTS = []
    NOTES = []
    CONCEPTS = []
    CONNECTIONS = []

log = logging.getLogger("knowledge")

router = APIRouter()


@router.post("/knowledge/build-context")
async def build_context(request: KnowledgeContextRequest):
    """
    Build a focused knowledge document for a specific topic and create a TerpAI agent with it.

    Entry points:
      1. Graph click:  { concept_id: "c330-cfg" }
      2. Free text:    { prompt: "study for my CFG exam" }
      3. Both:         { concept_id: "c330-cfg", prompt: "focus on parsing" }
    """
    query = request.prompt or ""
    course_filter = request.course_id

    if request.concept_id:
        concept = next((c for c in CONCEPTS if c["id"] == request.concept_id), None)
        if concept:
            query = f"{concept['label']} — {query}" if query else concept["label"]
            if not course_filter:
                course_filter = concept["course_id"]
        else:
            raise HTTPException(status_code=404, detail=f"Concept '{request.concept_id}' not found")

    if not query:
        raise HTTPException(status_code=400, detail="Provide either a 'prompt' or 'concept_id'")

    log.info(f"🧠 Building knowledge context for: \"{query}\" (course={course_filter})")

    try:
        prompt = build_topic_knowledge_prompt(
            query=query,
            concepts=CONCEPTS,
            assignments=ASSIGNMENTS,
            notes=NOTES,
            connections=CONNECTIONS,
            courses=COURSES,
            course_filter=course_filter,
        )
        context_doc = await build_knowledge_document(prompt)
        log.info(f"📄 Generated knowledge doc ({len(context_doc)} chars)")

        agent_url = None
        if bridge._ready:
            try:
                agent_name = f"Aether: {query[:40]}"
                agent_url = await bridge.create_topic_agent(agent_name, context_doc)
                log.info(f"✅ Agent created: {agent_url}")
                # Cache the knowledge doc so specialized agent chats can inject it
                bridge.store_agent_context(agent_url, context_doc)
            except Exception as e:
                log.warning(f"⚠️  Agent creation failed: {e}")

        return {
            "status": "success",
            "query": query,
            "course": course_filter,
            "agent_url": agent_url,
        }
    except Exception as e:
        log.error(f"❌ build-context failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/knowledge/refresh-from-graph")
async def refresh_from_graph(request: GraphRefreshRequest):
    """
    Analyze the knowledge graph with Gemini and update the main agent's context.
    """
    if not request.nodes:
        raise HTTPException(status_code=400, detail="Cannot refresh from empty graph")

    if not bridge._ready:
        return {"status": "skipped", "reason": "TerpAI bridge disconnected"}

    try:
        prompt = build_graph_analysis_prompt(
            nodes=request.nodes,
            edges=request.edges,
            mastery=request.mastery,
        )
        context_doc = await build_knowledge_document(prompt)
        log.info(f"📄 Graph knowledge doc ({len(context_doc)} chars)")

        await bridge.update_agent_knowledge(context_doc)
        log.info("✅ Graph synced into TerpAI")

        return {"status": "success", "message": "Graph successfully synced into TerpAI"}
    except Exception as e:
        log.error(f"❌ refresh-from-graph failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/knowledge/recommend-courses")
async def recommend_courses(request: CourseRecommendationRequest):
    """
    Recommend 3 future modules using the same build-context flow:
      1. Fetch the NTU CS module catalog (catalog_service)
      2. Build a knowledge doc via Gemini (build_knowledge_document)
      3. Create an agent with that context
      4. Extract 3 structured recommendations via generate_json_fallback
    """
    if not request.taken_course_ids:
        raise HTTPException(status_code=400, detail="taken_course_ids must not be empty")

    log.info(f"🎓 Recommending modules for taken={request.taken_course_ids}")

    try:
        # 1. Fetch the NTU CS module catalog
        all_modules = await catalog_service.fetch_all_courses("SCSE")
        catalog_available = bool(all_modules)
        if not catalog_available:
            log.warning("NTU catalog unavailable — courses added by ID only, suggesting manual entry")
        else:
            log.info(f"📚 Fetched {len(all_modules)} NTU modules from catalog")

        # Match taken module IDs to full module objects
        taken_upper = {cid.upper() for cid in request.taken_course_ids}
        taken_courses = [c for c in all_modules if c.get("course_id", "").upper() in taken_upper]
        unmatched_ids = taken_upper - {c.get("course_id", "").upper() for c in taken_courses}

        if not catalog_available or not taken_courses:
            return {
                "status": "partial",
                "message": (
                    "Your course(s) have been added, but we could not retrieve details from the NTU catalog. "
                    "Please manually add course details (name, credits, description) for accurate recommendations."
                ),
                "added_course_ids": list(request.taken_course_ids),
                "unmatched_ids": sorted(unmatched_ids),
                "recommendations": [],
                "agent_url": None,
            }

        # 2. Build knowledge document (Gemini) — mirrors build-context
        prompt = build_course_recommendation_prompt(
            taken_courses=taken_courses,
            all_cmsc_courses=all_modules,
        )
        context_doc = await build_knowledge_document(prompt)
        log.info(f"📄 Generated course recommendation doc ({len(context_doc)} chars)")

        # 3. Create TerpAI agent — mirrors build-context
        agent_url = None
        if bridge._ready:
            try:
                agent_name = "Aether: Course Advisor"
                agent_url = await bridge.create_topic_agent(agent_name, context_doc)
                log.info(f"✅ Course advisor agent created: {agent_url}")
                bridge.store_agent_context(agent_url, context_doc)
            except Exception as e:
                log.warning(f"⚠️  Agent creation failed: {e}")

        # 4. Extract structured recommendations (Gemini JSON)
        json_prompt = build_recommendation_json_prompt(context_doc, request.taken_course_ids)
        recommendations = await generate_json_fallback(json_prompt)
        if isinstance(recommendations, list):
            recommendations = recommendations[:3]
        log.info(f"✅ Got {len(recommendations)} course recommendations")

        return {
            "status": "success",
            "agent_url": agent_url,
            "recommendations": recommendations,
        }
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"❌ recommend-courses failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
