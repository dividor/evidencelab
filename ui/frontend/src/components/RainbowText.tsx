import React from 'react';

// Wave animation textual component
export const RainbowText = ({ text }: { text: string }) => {
    return (
        <span className="rainbow-text" style={{ display: 'inline-block' }}>
            {text.split('').map((char, index) => (
                <span
                    key={index}
                    className="wave-char"
                    style={{ animationDelay: `${index * 0.1}s`, display: 'inline-block' }}
                >
                    {char === ' ' ? '\u00A0' : char}
                </span>
            ))}
        </span>
    );
};
