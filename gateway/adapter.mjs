export function toGatewayQuestions(questions) {
 return Object.fromEntries(Object.entries(questions).map(([id,q])=> {
  if (!['choice','score','noul'].includes(q.type)) throw new Error('Unsupported question type');
  return [id,{...q,type:q.type==='noul'?'boolean':q.type}];
 }));
}
export function toPythonAnswers(answers) {
 return Object.fromEntries(Object.entries(answers).map(([id,a])=>[id,
  a.type==='boolean' ? {type:'noul',noul:a.probability} : {...a,confidence:null}
 ]));
}
