-- ACCEPT
UPDATE corrective_actions_vectors
SET accept_count = accept_count + 1,
    feedback_score = (accept_count + 1.0) / (accept_count + reject_count + 1),
    updated_at = NOW()
WHERE id = {vector_id}

-- REJECT  
UPDATE corrective_actions_vectors
SET reject_count = reject_count + 1,
    feedback_score = accept_count / (accept_count + reject_count + 1.0),
    updated_at = NOW()
WHERE id = {vector_id}