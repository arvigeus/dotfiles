import QtQuick
import "../movies"

Worker {
    objectName: "booksService"
    backend: "backend.py"
    backendDirectory: "spaces/books"
    spaceId: "books"
    serviceName: "Books"
    id: root
    property var jobs: []
    property int startingJobs: 0
    property bool pollingJobs: false
    property var jobRequests: ({})
    property var announcedJobs: ({})
    readonly property int activeJobCount: startingJobs + jobs.filter(j => j.state === "queued" || j.state === "running").length
    signal jobFinished(var job)
    signal jobStartFailed(string message)

    function startJob(op, args) {
        startingJobs++;
        request(op, args, (result, error) => {
            if (error || !result || !result.job_id) {
                startingJobs = Math.max(0, startingJobs - 1);
                jobStartFailed(error || "Could not start this operation.");
                return;
            }
            jobRequests[result.job_id] = {op: op, args: args};
            if (!jobs.some(job => job.job_id === result.job_id)) jobs = jobs.concat([{job_id: result.job_id, title: args.title || "Transfer", state: "queued", done: 0, total: 0, detail: "Preparing…"}]);
            startingJobs = Math.max(0, startingJobs - 1);
            pollJobs();
        });
    }
    function retryJob(id) {
        const entry = jobRequests[id];
        if (entry) startJob(entry.op, entry.args);
    }
    function cancelJob(id) {
        request("cancel_job", {job_id: id}, (result, error) => { if (error) jobStartFailed(error); });
    }
    function pollJobs() {
        if (pollingJobs || stopped) return;
        pollingJobs = true;
        request("jobs", {}, (result, error) => {
            pollingJobs = false;
            if (error) {
                if (stopped) {
                    for (const job of jobs.filter(j => j.state === "queued" || j.state === "running"))
                        jobFinished(Object.assign({}, job, {state: "failed", error: error}));
                    jobs = [];
                }
                return;
            }
            const snapshot = (result.jobs || []).map(job => {
                if (["failed", "cancelled"].includes(job.state) && jobRequests[job.job_id])
                    return Object.assign({}, job, {actionLabel: "Retry"});
                return job;
            });
            for (const job of snapshot) {
                if (["finished", "failed", "cancelled"].includes(job.state) && !announcedJobs[job.job_id]) {
                    announcedJobs[job.job_id] = true;
                    jobFinished(job);
                }
            }
            // A jobs response can predate another start response. Keep accepted
            // jobs until a newer snapshot has actually observed them.
            const ids = snapshot.map(j => j.job_id);
            jobs = snapshot.concat(jobs.filter(j => ["queued", "running"].includes(j.state) && !ids.includes(j.job_id)));
            const retained = jobs.map(j => j.job_id);
            for (const key of Object.keys(announcedJobs))
                if (!retained.includes(key)) delete announcedJobs[key];
            for (const key of Object.keys(jobRequests))
                if (!retained.includes(key)) delete jobRequests[key];
        });
    }
    onStoppedChanged: { if (stopped) { jobs = []; startingJobs = 0; jobRequests = {}; announcedJobs = {}; } }
    Timer { interval: 700; repeat: true; running: root.activeJobCount > 0; onTriggered: root.pollJobs() }
}
