import React, { useState, useEffect } from 'react';
import axios from 'axios';
import API_BASE_URL from '../config';

interface QueueModalProps {
    isOpen: boolean;
    onClose: () => void;
    dataSource?: string;
}

interface TaskInfo {
    id: string;
    name: string;
    args: any[];
    kwargs: any;
    time_start?: number;
    acknowledged?: boolean;
    worker_pid?: number;
    output?: string;
}

interface QueueData {
    active: Record<string, TaskInfo[]>;
    reserved: Record<string, TaskInfo[]>;
    scheduled: Record<string, TaskInfo[]>;
    error?: string;
}

const QueueTaskOutput = ({ output }: { output?: string }) => {
    if (!output) {
        return null;
    }

    return (
        <div
            style={{
                marginTop: '8px',
                padding: '8px',
                background: '#f1f5f9',
                borderRadius: '4px',
                fontSize: '0.85em',
                fontFamily: 'monospace',
                whiteSpace: 'pre-wrap',
                color: '#334155',
                maxHeight: '200px',
                overflowY: 'auto',
                border: '1px solid #e2e8f0'
            }}
        >
            {output}
        </div>
    );
};

const QueueTaskList = ({
    tasksMap,
    label
}: {
    tasksMap: Record<string, TaskInfo[]>;
    label: string;
}) => {
    const allTasks: TaskInfo[] = [];
    Object.values(tasksMap).forEach((taskList) => {
        allTasks.push(...taskList);
    });

    if (allTasks.length === 0) {
        return <div className="queue-empty-state">No {label} tasks</div>;
    }

    return (
        <div className="queue-task-list">
            {allTasks.map((task) => (
                <div key={task.id} className="queue-task-item">
                    <div className="queue-task-header">
                        <span className="queue-task-name">{task.name}</span>
                        <span className="queue-task-id">{task.id}</span>
                    </div>
                    <div className="queue-task-details">
                        args: {JSON.stringify(task.args)}
                        <QueueTaskOutput output={task.output} />
                    </div>
                </div>
            ))}
        </div>
    );
};

const QueueModalBody = ({ data }: { data: QueueData | null }) => {
    if (!data) {
        return <div>Loading...</div>;
    }

    if (data.error) {
        return <div className="error-message">Error: {data.error}</div>;
    }

    return (
        <div className="queue-sections">
            <div className="queue-section">
                <h4>Active (Running)</h4>
                <QueueTaskList tasksMap={data.active} label="active" />
            </div>

            <div className="queue-section">
                <h4>Reserved (Waiting)</h4>
                <QueueTaskList tasksMap={data.reserved} label="reserved" />
            </div>

            <div className="queue-section">
                <h4>Scheduled</h4>
                <QueueTaskList tasksMap={data.scheduled} label="scheduled" />
            </div>
        </div>
    );
};

const QueueModalFooter = ({
    lastUpdated,
    loading,
    onClose
}: {
    lastUpdated: Date | null;
    loading: boolean;
    onClose: () => void;
}) => (
    <div
        className="modal-footer"
        style={{
            padding: '20px 24px',
            borderTop: '1px solid #eee',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center'
        }}
    >
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            {lastUpdated && (
                <span
                    className="last-updated"
                    style={{ color: '#666', fontSize: '0.875rem' }}
                >
                    Last updated: {lastUpdated.toLocaleTimeString()}
                </span>
            )}
            {loading && (
                <span style={{ color: '#0ea5e9', fontSize: '0.875rem', fontWeight: 500 }}>
                    Refreshing...
                </span>
            )}
        </div>
        <button
            className="btn-secondary"
            onClick={onClose}
            style={{
                padding: '8px 24px',
                borderRadius: '6px',
                border: '1px solid #ddd',
                background: '#fff',
                cursor: 'pointer',
                color: '#333',
                fontSize: '0.875rem',
                fontWeight: 500
            }}
        >
            Close
        </button>
    </div>
);

const QueueModal: React.FC<QueueModalProps> = ({ isOpen, onClose, dataSource }) => {
    const [data, setData] = useState<QueueData | null>(null);
    const [loading, setLoading] = useState(false);
    const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

    const fetchQueueStatus = async () => {
        try {
            setLoading(true);
            const response = await axios.get(`${API_BASE_URL}/queue/status`);
            const data = response.data as QueueData;
            setData(data);
            setLastUpdated(new Date());
        } catch (err) {
            console.error("Error fetching queue status:", err);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        if (isOpen) {
            fetchQueueStatus();
            // Auto-refresh every 3 seconds
            const interval = setInterval(fetchQueueStatus, 3000);
            return () => clearInterval(interval);
        }
    }, [isOpen]);

    if (!isOpen) return null;

    return (
        <div className="preview-overlay" onClick={onClose}>
            <div className="modal-panel queue-modal" onClick={e => e.stopPropagation()} style={{ minHeight: '400px' }}>
                <div className="modal-header">
                    <h3>Task Queue Status</h3>
                    <button className="modal-close" onClick={onClose}>&times;</button>
                </div>

                <div className="modal-body" style={{ flex: 1, padding: '24px' }}>
                    <QueueModalBody data={data} />
                </div>

                <QueueModalFooter
                    lastUpdated={lastUpdated}
                    loading={loading}
                    onClose={onClose}
                />
            </div>
        </div>
    );
};

export default QueueModal;
